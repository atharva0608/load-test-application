"""
StressForge Cluster Router — HPA observer, replica count, K8s status.
Provides simulated data in Docker Compose mode, real K8s data when running in-cluster.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
import os
import logging
import random

logger = logging.getLogger("stressforge.cluster")

router = APIRouter(prefix="/api/cluster", tags=["Cluster"])


class HPAStatus(BaseModel):
    current_replicas: int
    desired_replicas: int
    min_replicas: int
    max_replicas: int
    cpu_utilization_percent: float
    target_cpu_percent: int
    scaling_status: str  # "stable", "scaling_up", "scaling_down"
    mode: str  # "kubernetes" or "docker-compose"


class ClusterInfo(BaseModel):
    node_count: int
    pod_count: int
    namespace: str
    cluster_name: str
    mode: str


def is_kubernetes():
    """Check if running inside a Kubernetes cluster."""
    return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")


@router.get("/hpa", response_model=HPAStatus)
def get_hpa_status():
    """
    Current HPA status — replica count, CPU utilization, scaling state.
    Returns real K8s data when running in-cluster, simulated data in Docker Compose.
    """
    if is_kubernetes():
        return _get_real_hpa()
    else:
        return _get_simulated_hpa()


@router.get("/info", response_model=ClusterInfo)
def get_cluster_info():
    """Cluster information — node count, pod count, namespace."""
    if is_kubernetes():
        return _get_real_cluster_info()
    else:
        return ClusterInfo(
            node_count=1,
            pod_count=6,  # api, worker, postgres, redis, frontend, locust
            namespace="default",
            cluster_name="docker-compose",
            mode="docker-compose",
        )


def _get_simulated_hpa() -> HPAStatus:
    """Simulated HPA data for Docker Compose mode."""
    # Generate realistic-looking data that varies slightly
    import time
    seed = int(time.time() / 30)  # Changes every 30 seconds
    random.seed(seed)

    current = random.choice([1, 1, 1, 2, 2, 3])
    desired = current + random.choice([0, 0, 0, 1, -1])
    desired = max(1, min(desired, 10))
    cpu = random.uniform(15, 75)

    if desired > current:
        status = "scaling_up"
    elif desired < current:
        status = "scaling_down"
    else:
        status = "stable"

    random.seed()  # Reset seed

    return HPAStatus(
        current_replicas=current,
        desired_replicas=desired,
        min_replicas=1,
        max_replicas=10,
        cpu_utilization_percent=round(cpu, 1),
        target_cpu_percent=50,
        scaling_status=status,
        mode="docker-compose",
    )


def _get_real_hpa() -> HPAStatus:
    """Read HPA status from the Kubernetes API."""
    try:
        # Read in-cluster config
        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

        with open(token_path) as f:
            token = f.read().strip()
        with open(ns_path) as f:
            namespace = f.read().strip()

        import urllib.request
        import ssl
        import json

        ctx = ssl.create_default_context(cafile=ca_path)
        api_host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        api_port = os.getenv("KUBERNETES_SERVICE_PORT", "443")

        url = f"https://{api_host}:{api_port}/apis/autoscaling/v2/namespaces/{namespace}/horizontalpodautoscalers"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")

        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            data = json.loads(resp.read())

        hpa_list = data.get("items", [])
        if not hpa_list:
            return _get_simulated_hpa()

        # Find the API HPA
        hpa = hpa_list[0]
        for h in hpa_list:
            if "api" in h["metadata"]["name"].lower() or "stressforge" in h["metadata"]["name"].lower():
                hpa = h
                break

        spec = hpa.get("spec", {})
        status = hpa.get("status", {})

        current = status.get("currentReplicas", 1)
        desired = status.get("desiredReplicas", 1)
        min_rep = spec.get("minReplicas", 1)
        max_rep = spec.get("maxReplicas", 10)

        # Get CPU utilization from metrics
        cpu_util = 0.0
        for metric in status.get("currentMetrics", []):
            if metric.get("type") == "Resource" and metric.get("resource", {}).get("name") == "cpu":
                cpu_util = metric["resource"]["current"].get("averageUtilization", 0)

        target_cpu = 50
        for metric in spec.get("metrics", []):
            if metric.get("type") == "Resource" and metric.get("resource", {}).get("name") == "cpu":
                target_cpu = metric["resource"]["target"].get("averageUtilization", 50)

        if desired > current:
            scaling = "scaling_up"
        elif desired < current:
            scaling = "scaling_down"
        else:
            scaling = "stable"

        return HPAStatus(
            current_replicas=current,
            desired_replicas=desired,
            min_replicas=min_rep,
            max_replicas=max_rep,
            cpu_utilization_percent=round(cpu_util, 1),
            target_cpu_percent=target_cpu,
            scaling_status=scaling,
            mode="kubernetes",
        )

    except Exception as e:
        logger.error(f"K8s HPA read failed: {e}")
        return _get_simulated_hpa()


def _get_real_cluster_info() -> ClusterInfo:
    """Read cluster info from the Kubernetes API."""
    try:
        token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ca_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        ns_path = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"

        with open(token_path) as f:
            token = f.read().strip()
        with open(ns_path) as f:
            namespace = f.read().strip()

        import urllib.request
        import ssl
        import json

        ctx = ssl.create_default_context(cafile=ca_path)
        api_host = os.getenv("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
        api_port = os.getenv("KUBERNETES_SERVICE_PORT", "443")

        # Get nodes
        url = f"https://{api_host}:{api_port}/api/v1/nodes"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            nodes_data = json.loads(resp.read())
        node_count = len(nodes_data.get("items", []))

        # Get pods in namespace
        url = f"https://{api_host}:{api_port}/api/v1/namespaces/{namespace}/pods"
        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, context=ctx, timeout=5) as resp:
            pods_data = json.loads(resp.read())
        pod_count = len(pods_data.get("items", []))

        return ClusterInfo(
            node_count=node_count,
            pod_count=pod_count,
            namespace=namespace,
            cluster_name=os.getenv("CLUSTER_NAME", "stressforge-cluster"),
            mode="kubernetes",
        )

    except Exception as e:
        logger.error(f"K8s cluster info failed: {e}")
        return ClusterInfo(
            node_count=0,
            pod_count=0,
            namespace="unknown",
            cluster_name="unknown",
            mode="kubernetes",
        )
