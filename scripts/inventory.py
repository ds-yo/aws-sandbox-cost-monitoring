#!/usr/bin/env python3
"""コストが発生しているリージョンのリソースを読み取り専用 API で棚卸しする。

cost_breakdown.json の使用タイプ（例: NatGateway-Hours）を具体的なリソース ID に結び付けるために使う。
describe / list 系 API のみ使用（.claude/rules/aws-access.md）。権限不足は errors に記録して継続する。
出力: out/<YYYY-MM>/inventory.json

使い方:
    .venv/bin/python scripts/inventory.py --month 2026-09 [--force]
"""

import argparse
import json
import os
import sys
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import boto3

ROOT = Path(__file__).resolve().parent.parent
MIN_REGION_USD = 1.0
NON_REGIONS = {"NoRegion", "global"}


def _name(tags: list[dict] | None) -> str:
    return next((t["Value"] for t in tags or [] if t["Key"] == "Name"), "")


def _tags(tags: list[dict] | None) -> dict:
    return {t["Key"]: t["Value"] for t in tags or []}


def _iso(v) -> str | None:
    return v.isoformat() if hasattr(v, "isoformat") else v


def _pages(client, op: str, key: str, **kwargs) -> list[dict]:
    if client.can_paginate(op):
        return [item for page in client.get_paginator(op).paginate(**kwargs) for item in page.get(key, [])]
    return getattr(client, op)(**kwargs).get(key, [])


def nat_gateways(s) -> list[dict]:
    ec2 = s.client("ec2")
    return [
        {
            "id": n["NatGatewayId"],
            "name": _name(n.get("Tags")),
            "vpc_id": n.get("VpcId"),
            "subnet_id": n.get("SubnetId"),
            "connectivity": n.get("ConnectivityType"),
            "created": _iso(n.get("CreateTime")),
            "tags": _tags(n.get("Tags")),
        }
        for n in _pages(ec2, "describe_nat_gateways", "NatGateways", Filter=[{"Name": "state", "Values": ["available"]}])
    ]


def elastic_ips(s) -> list[dict]:
    ec2 = s.client("ec2")
    return [
        {
            "allocation_id": a.get("AllocationId"),
            "public_ip": a.get("PublicIp"),
            "associated": bool(a.get("AssociationId")),
            "instance_id": a.get("InstanceId"),
            "network_interface_id": a.get("NetworkInterfaceId"),
            "name": _name(a.get("Tags")),
            "tags": _tags(a.get("Tags")),
        }
        for a in ec2.describe_addresses().get("Addresses", [])
    ]


def public_ipv4_on_enis(s) -> dict:
    ec2 = s.client("ec2")
    enis = _pages(ec2, "describe_network_interfaces", "NetworkInterfaces")
    by_type: dict[str, int] = {}
    for e in enis:
        if e.get("Association", {}).get("PublicIp"):
            t = e.get("InterfaceType", "interface")
            by_type[t] = by_type.get(t, 0) + 1
    return {"public_ip_count_by_interface_type": by_type, "eni_count": len(enis)}


def vpc_endpoints(s) -> list[dict]:
    ec2 = s.client("ec2")
    return [
        {
            "id": v["VpcEndpointId"],
            "type": v.get("VpcEndpointType"),
            "service": v.get("ServiceName"),
            "vpc_id": v.get("VpcId"),
            "az_count": len(v.get("SubnetIds", [])),
            "state": v.get("State"),
            "created": _iso(v.get("CreationTimestamp")),
            "tags": _tags(v.get("Tags")),
        }
        for v in _pages(ec2, "describe_vpc_endpoints", "VpcEndpoints")
        if v.get("VpcEndpointType") != "Gateway"  # Gateway 型（S3/DynamoDB）は無料
    ]


def vpcs(s) -> list[dict]:
    ec2 = s.client("ec2")
    return [
        {"id": v["VpcId"], "name": _name(v.get("Tags")), "cidr": v.get("CidrBlock"), "is_default": v.get("IsDefault")}
        for v in _pages(ec2, "describe_vpcs", "Vpcs")
    ]


def ec2_instances(s) -> list[dict]:
    ec2 = s.client("ec2")
    return [
        {
            "id": i["InstanceId"],
            "name": _name(i.get("Tags")),
            "type": i.get("InstanceType"),
            "state": i["State"]["Name"],
            "lifecycle": i.get("InstanceLifecycle", "on-demand"),
            "launch_time": _iso(i.get("LaunchTime")),
            "vpc_id": i.get("VpcId"),
            "tags": _tags(i.get("Tags")),
        }
        for r in _pages(ec2, "describe_instances", "Reservations")
        for i in r["Instances"]
        if i["State"]["Name"] != "terminated"
    ]


def ebs_volumes(s) -> list[dict]:
    ec2 = s.client("ec2")
    return [
        {
            "id": v["VolumeId"],
            "size_gb": v["Size"],
            "type": v["VolumeType"],
            "state": v["State"],
            "attached_to": [a["InstanceId"] for a in v.get("Attachments", [])],
            "created": _iso(v.get("CreateTime")),
            "name": _name(v.get("Tags")),
        }
        for v in _pages(ec2, "describe_volumes", "Volumes")
    ]


def load_balancers(s) -> list[dict]:
    elb = s.client("elbv2")
    return [
        {
            "name": lb["LoadBalancerName"],
            "type": lb["Type"],
            "scheme": lb.get("Scheme"),
            "vpc_id": lb.get("VpcId"),
            "state": lb.get("State", {}).get("Code"),
            "created": _iso(lb.get("CreatedTime")),
        }
        for lb in _pages(elb, "describe_load_balancers", "LoadBalancers")
    ]


def rds(s) -> dict:
    client = s.client("rds")
    return {
        "instances": [
            {
                "id": d["DBInstanceIdentifier"],
                "class": d["DBInstanceClass"],
                "engine": d["Engine"],
                "status": d["DBInstanceStatus"],
                "multi_az": d.get("MultiAZ"),
                "storage_gb": d.get("AllocatedStorage"),
                "storage_type": d.get("StorageType"),
                "cluster": d.get("DBClusterIdentifier"),
                "created": _iso(d.get("InstanceCreateTime")),
            }
            for d in _pages(client, "describe_db_instances", "DBInstances")
        ],
        "clusters": [
            {
                "id": c["DBClusterIdentifier"],
                "engine": c["Engine"],
                "status": c["Status"],
                "serverless_v2": c.get("ServerlessV2ScalingConfiguration"),
                "multi_az": c.get("MultiAZ"),
                "created": _iso(c.get("ClusterCreateTime")),
            }
            for c in _pages(client, "describe_db_clusters", "DBClusters")
        ],
    }


def network_firewalls(s) -> list[dict]:
    nf = s.client("network-firewall")
    result = []
    for f in _pages(nf, "list_firewalls", "Firewalls"):
        d = nf.describe_firewall(FirewallArn=f["FirewallArn"])["Firewall"]
        result.append(
            {
                "name": d["FirewallName"],
                "vpc_id": d.get("VpcId"),
                "endpoint_count": len(d.get("SubnetMappings", [])),
                "tags": _tags(d.get("Tags")),
            }
        )
    return result


def workspaces(s) -> list[dict]:
    ws = s.client("workspaces")
    return [
        {
            "id": w["WorkspaceId"],
            "user": w.get("UserName"),
            "state": w.get("State"),
            "running_mode": w.get("WorkspaceProperties", {}).get("RunningMode"),
            "compute": w.get("WorkspaceProperties", {}).get("ComputeTypeName"),
        }
        for w in _pages(ws, "describe_workspaces", "Workspaces")
    ]


def directories(s) -> list[dict]:
    ds = s.client("ds")
    return [
        {"id": d["DirectoryId"], "name": d.get("Name"), "type": d.get("Type"), "size": d.get("Size"), "stage": d.get("Stage")}
        for d in ds.describe_directories().get("DirectoryDescriptions", [])
    ]


def redshift(s) -> dict:
    return {
        "clusters": [
            {"id": c["ClusterIdentifier"], "node_type": c["NodeType"], "nodes": c["NumberOfNodes"], "status": c["ClusterStatus"]}
            for c in _pages(s.client("redshift"), "describe_clusters", "Clusters")
        ],
        "serverless_workgroups": [
            {"name": w["workgroupName"], "base_capacity": w.get("baseCapacity"), "status": w.get("status")}
            for w in _pages(s.client("redshift-serverless"), "list_workgroups", "workgroups")
        ],
    }


COLLECTORS: dict[str, Callable] = {
    "nat_gateways": nat_gateways,
    "elastic_ips": elastic_ips,
    "public_ipv4": public_ipv4_on_enis,
    "vpc_endpoints": vpc_endpoints,
    "vpcs": vpcs,
    "ec2_instances": ec2_instances,
    "ebs_volumes": ebs_volumes,
    "load_balancers": load_balancers,
    "rds": rds,
    "network_firewalls": network_firewalls,
    "workspaces": workspaces,
    "directories": directories,
    "redshift": redshift,
}


def cost_regions(breakdown: dict) -> list[str]:
    totals: dict[str, float] = {}
    for r in breakdown["region_by_service"]:
        if r["region"] not in NON_REGIONS:
            totals[r["region"]] = totals.get(r["region"], 0.0) + r["amount_usd"]
    return [k for k, v in sorted(totals.items(), key=lambda kv: kv[1], reverse=True) if v >= MIN_REGION_USD]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--month", required=True, help="対象月 YYYY-MM（cost_breakdown.json のリージョンを使う）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    out_dir = ROOT / "out" / args.month
    out_path = out_dir / "inventory.json"
    if out_path.exists() and not args.force:
        print(f"取得済みのため再利用します: {out_path}（再取得は --force）")
        return 0
    breakdown_path = out_dir / "cost_breakdown.json"
    if not breakdown_path.exists():
        print("先に scripts/fetch_breakdown.py を実行してください", file=sys.stderr)
        return 1

    profile = os.environ.get("AWS_PROFILE", "sandbox-mfa")
    regions = cost_regions(json.loads(breakdown_path.read_text()))
    result: dict = {"generated_at": datetime.now(timezone.utc).isoformat(), "regions": {}, "errors": []}
    for region in regions:
        s = boto3.Session(profile_name=profile, region_name=region)
        data: dict = {}
        for key, fn in COLLECTORS.items():
            try:
                data[key] = fn(s)
            except Exception as e:  # noqa: BLE001 - 権限不足・未提供リージョンでも継続
                result["errors"].append({"region": region, "collector": key, "error": f"{type(e).__name__}: {str(e)[:200]}"})
        result["regions"][region] = data

    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    print(f"保存しました: {out_path}（リージョン: {', '.join(regions)} / エラー {len(result['errors'])} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
