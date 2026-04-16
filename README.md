# 🏗️ StressForge — Infrastructure Load Testing Target

> A production-grade, multi-service application designed to put **real load** on your Kubernetes infrastructure. Built for **Locust** load simulation.

![Architecture](https://img.shields.io/badge/Architecture-Multi--Arch-blue) ![Docker](https://img.shields.io/badge/Docker-Compose-2496ED) ![K8s](https://img.shields.io/badge/Kubernetes-Ready-326CE5) ![Python](https://img.shields.io/badge/Python-3.12-3776AB)

---

## 🏛️ Architecture

| Service | Type | K8s Resource | Port | Purpose |
|---------|------|-------------|------|---------|
| **PostgreSQL** | Database | StatefulSet | 5432 | Persistent relational data |
| **Redis** | Cache | StatefulSet | 6379 | Caching + Celery broker |
| **API Server** | Backend | Deployment (HPA) | 8000 | FastAPI REST API |
| **Celery Worker** | Worker | Deployment | — | Background task processing |
| **Frontend** | Dashboard | Deployment | 3000 | Premium SPA dashboard |
| **Locust** | Load Testing | Job/Deployment | 8089 | Load generation |

## 🚀 Quick Start

### Prerequisites
- Docker Desktop with Docker Compose v2
- At least 4 GB RAM allocated to Docker

### Run
```bash
# Clone and start everything
cd "TEST Application"
docker compose up --build

# Or detached mode
docker compose up --build -d
```

### Access
| Service | URL |
|---------|-----|
| 🖥️ **Dashboard** | [http://localhost:3000](http://localhost:3000) |
| ⚡ **API Docs** | [http://localhost:8000/api/docs](http://localhost:8000/api/docs) |
| 🦗 **Locust** | [http://localhost:8089](http://localhost:8089) |
| 🐘 **PostgreSQL** | `localhost:5432` |
| 🔴 **Redis** | `localhost:6379` |

## 📊 API Endpoints

### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/auth/register` | Register new user (bcrypt CPU load) |
| POST | `/api/auth/login` | Login with JWT |

### Products
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/products` | List with pagination + filters |
| GET | `/api/products/{id}` | Get single (Redis cached) |
| GET | `/api/products/search?q=` | Full-text search |
| GET | `/api/products/categories` | List categories |
| POST | `/api/products` | Create product (auth required) |

### Orders
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/orders` | Place order (multi-table txn) |
| GET | `/api/orders` | List user orders |
| GET | `/api/orders/{id}` | Get order details |
| POST | `/api/orders/bulk` | Bulk create (I/O stress) |
| GET | `/api/orders/stats` | Aggregate statistics |

### Stress Testing
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/stress/cpu` | Fibonacci + matrix + SHA-256 |
| POST | `/api/stress/memory` | Large array allocation |
| POST | `/api/stress/io` | Heavy DB queries + file ops |
| POST | `/api/stress/mixed` | Combined CPU+Memory+IO |

### Health & Metrics
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/health` | Liveness probe |
| GET | `/api/health/ready` | Readiness probe (DB+Redis) |
| GET | `/api/metrics` | System metrics |

## 🦗 Load Testing with Locust

### Using the Built-in Locust
1. Start the stack: `docker compose up --build`
2. Open [http://localhost:8089](http://localhost:8089)
3. Set users (e.g., 50) and spawn rate (e.g., 5/s)
4. Click **Start swarming**

### User Personas
| Persona | Weight | Behavior |
|---------|--------|----------|
| **BrowsingUser** | 5 | Read-heavy: product catalog, search |
| **ShoppingUser** | 3 | Registers, places orders, browses |
| **StressUser** | 2 | Hits CPU/Memory/IO stress endpoints |

## 🐳 Multi-Architecture Build

```bash
# Build for both amd64 and arm64
docker buildx create --use --name stressforge-builder
docker buildx build --platform linux/amd64,linux/arm64 -t stressforge/api:latest ./backend
docker buildx build --platform linux/amd64,linux/arm64 -t stressforge/frontend:latest ./frontend
docker buildx build --platform linux/amd64,linux/arm64 -t stressforge/worker:latest -f worker/Dockerfile .
docker buildx build --platform linux/amd64,linux/arm64 -t stressforge/locust:latest ./locust
```

## ☸️ Kubernetes Deployment

```bash
kubectl apply -f k8s/namespace.yml
kubectl apply -f k8s/postgres-statefulset.yml
kubectl apply -f k8s/redis-statefulset.yml
kubectl apply -f k8s/api-deployment.yml
kubectl apply -f k8s/worker-frontend-deployment.yml
kubectl apply -f k8s/ingress.yml
```

## 🧹 Cleanup

```bash
# Docker
docker compose down -v

# Kubernetes
kubectl delete namespace stressforge
```
