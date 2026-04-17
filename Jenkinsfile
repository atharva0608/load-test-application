pipeline {
    agent any

    environment {
        // Core configuration
        DOCKER_HUB_USER = 'atharva608'
        APP_NAME = 'stressforge'
        // STRICT GIT-OPS: We only use the deterministic Jenkins BUILD_NUMBER as our tag. 
        // No 'latest' tags are pushed to avoid untraceable config drift.
        DOCKER_TAG = "${env.BUILD_NUMBER}"
        
        // Explicitly defined image names
        API_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-api"
        FRONTEND_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-frontend"
        WORKER_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-worker"
        LOCUST_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-locust"

        // EKS cluster config
        CLUSTER_NAME = 'spot-demo-1'
        AWS_REGION   = 'ap-south-1'
    }

    stages {
        stage('Checkout') {
            steps {
                // Completely clean the workspace to prevent "fatal: not in a git directory" corruption
                deleteDir()
                // Explicit Git checkout using the correct credentials id
                git branch: 'staging', credentialsId: 'Github-Ecc', url: 'https://github.com/atharva0608/load-test-application.git'
            }
        }

        stage('Bootstrap Tools') {
            steps {
                sh '''
                set -e

                echo "🔧 Bootstrapping CI tools..."

                # ----------------------------
                # Ensure we are root
                # ----------------------------
                if [ "$(id -u)" -ne 0 ]; then
                  echo "❌ Must run as root to install dependencies"
                  exit 1
                fi

                # ----------------------------
                # Install base tools
                # ----------------------------
                if ! command -v curl >/dev/null 2>&1; then
                  echo "Installing curl..."
                  apt-get update
                  apt-get install -y curl
                fi

                if ! command -v git >/dev/null 2>&1; then
                  echo "Installing git..."
                  apt-get update
                  apt-get install -y git
                fi

                # ----------------------------
                # Install Docker CLI (fallback)
                # ----------------------------
                if ! command -v docker >/dev/null 2>&1; then
                  echo "Installing Docker CLI..."
                  apt-get update
                  apt-get install -y docker.io
                fi

                # ----------------------------
                # Verify Docker daemon access
                # ----------------------------
                if ! docker ps >/dev/null 2>&1; then
                  echo "❌ Docker daemon not accessible"
                  exit 1
                fi

                # ----------------------------
                # Detect Architecture
                # ----------------------------
                ARCH=$(uname -m)
                if [ "$ARCH" = "x86_64" ]; then
                    COMPOSE_ARCH="x86_64"
                    BUILDX_ARCH="amd64"
                    YQ_ARCH="amd64"
                elif [ "$ARCH" = "aarch64" ] || [ "$ARCH" = "arm64" ]; then
                    COMPOSE_ARCH="aarch64"
                    BUILDX_ARCH="arm64"
                    YQ_ARCH="arm64"
                else
                    echo "❌ Unsupported architecture: $ARCH"
                    exit 1
                fi

                # ----------------------------
                # Install Docker Compose v2 plugin natively
                # ----------------------------
                mkdir -p /usr/libexec/docker/cli-plugins
                echo "Installing Docker Compose plugin ($COMPOSE_ARCH)..."
                curl -SL "https://github.com/docker/compose/releases/latest/download/docker-compose-linux-${COMPOSE_ARCH}" \
                  -o /usr/libexec/docker/cli-plugins/docker-compose
                chmod +x /usr/libexec/docker/cli-plugins/docker-compose

                # ----------------------------
                # Install Docker Buildx plugin natively (Required >=0.17 for compose build)
                # ----------------------------
                echo "Installing Docker Buildx plugin ($BUILDX_ARCH)..."
                curl -SL "https://github.com/docker/buildx/releases/download/v0.19.1/buildx-v0.19.1.linux-${BUILDX_ARCH}" \
                  -o /usr/libexec/docker/cli-plugins/docker-buildx
                chmod +x /usr/libexec/docker/cli-plugins/docker-buildx

                # ----------------------------
                # Install yq
                # ----------------------------
                if ! command -v yq >/dev/null 2>&1; then
                  echo "Installing yq ($YQ_ARCH)..."
                  curl -SL "https://github.com/mikefarah/yq/releases/latest/download/yq_linux_${YQ_ARCH}" \
                    -o /usr/local/bin/yq
                  chmod +x /usr/local/bin/yq
                fi

                # ----------------------------
                # Install AWS CLI v2
                # ----------------------------
                if ! command -v aws >/dev/null 2>&1; then
                  echo "Installing AWS CLI..."
                  apt-get update -qq && apt-get install -y -qq unzip
                  if [ "$ARCH" = "aarch64" ]; then
                    curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-aarch64.zip" -o /tmp/awscliv2.zip
                  else
                    curl -sSL "https://awscli.amazonaws.com/awscli-exe-linux-x86_64.zip" -o /tmp/awscliv2.zip
                  fi
                  cd /tmp && unzip -q awscliv2.zip && ./aws/install && cd -
                  rm -rf /tmp/awscliv2.zip /tmp/aws
                fi

                # ----------------------------
                # Install kubectl
                # ----------------------------
                if ! command -v kubectl >/dev/null 2>&1; then
                  echo "Installing kubectl..."
                  KUBECTL_VERSION=$(curl -sSL https://dl.k8s.io/release/stable.txt)
                  curl -sSLO "https://dl.k8s.io/release/${KUBECTL_VERSION}/bin/linux/${BUILDX_ARCH}/kubectl"
                  chmod +x kubectl && mv kubectl /usr/local/bin/kubectl
                fi

                # ----------------------------
                # Install openssl (for OIDC thumbprint)
                # ----------------------------
                if ! command -v openssl >/dev/null 2>&1; then
                  apt-get update -qq && apt-get install -y -qq openssl
                fi

                echo "✅ All tools ready"
                aws --version
                kubectl version --client

                # ----------------------------
                # Print versions (debug)
                # ----------------------------
                docker --version
                docker compose version
                yq --version
                git --version
                curl --version
                '''
            }
        }

        stage('Bootstrap EKS Infrastructure') {
            steps {
                sh '''
                set -e

                echo "🔧 Ensuring EKS infrastructure is ready..."

                # ── Read from Jenkins environment block (change only those two lines to retarget) ──
                CLUSTER_NAME="${CLUSTER_NAME}"
                REGION="${AWS_REGION}"
                ROLE_NAME="AmazonEKS_EBS_CSI_DriverRole_${CLUSTER_NAME}"
                EBS_POLICY_ARN="arn:aws:iam::aws:policy/service-role/AmazonEBSCSIDriverPolicy"

                # ── Configure kubectl ──────────────────────────────────
                aws eks update-kubeconfig --name "$CLUSTER_NAME" --region "$REGION"
                echo "✅ kubeconfig updated"

                # ── Collect cluster identity ───────────────────────────
                ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
                OIDC_ID=$(aws eks describe-cluster --name "$CLUSTER_NAME" --region "$REGION" \
                  --query 'cluster.identity.oidc.issuer' --output text | cut -d'/' -f5)
                OIDC_PROVIDER="oidc.eks.${REGION}.amazonaws.com/id/${OIDC_ID}"
                OIDC_ARN="arn:aws:iam::${ACCOUNT_ID}:oidc-provider/${OIDC_PROVIDER}"

                echo "Account   : $ACCOUNT_ID"
                echo "OIDC ID   : $OIDC_ID"
                echo "OIDC ARN  : $OIDC_ARN"

                # ── Create OIDC provider if missing ────────────────────
                if aws iam get-open-id-connect-provider --open-id-connect-provider-arn "$OIDC_ARN" > /dev/null 2>&1; then
                  echo "✅ OIDC provider already exists"
                else
                  echo "Creating OIDC provider..."
                  THUMBPRINT=$(openssl s_client \
                    -connect "oidc.eks.${REGION}.amazonaws.com:443" \
                    -servername "oidc.eks.${REGION}.amazonaws.com" \
                    -showcerts </dev/null 2>/dev/null \
                    | openssl x509 -fingerprint -sha1 -noout \
                    | sed 's/.*=//;s/://g' | tr '[:upper:]' '[:lower:]')
                  aws iam create-open-id-connect-provider \
                    --url "https://${OIDC_PROVIDER}" \
                    --client-id-list sts.amazonaws.com \
                    --thumbprint-list "$THUMBPRINT"
                  echo "✅ OIDC provider created"
                fi

                # ── Create IAM role if missing ─────────────────────────
                if aws iam get-role --role-name "$ROLE_NAME" > /dev/null 2>&1; then
                  echo "✅ IAM role already exists"
                else
                  echo "Creating EBS CSI IAM role..."
                  cat > /tmp/ebs-trust.json << TRUSTEOF
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Federated": "${OIDC_ARN}"},
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": {
        "${OIDC_PROVIDER}:aud": "sts.amazonaws.com",
        "${OIDC_PROVIDER}:sub": "system:serviceaccount:kube-system:ebs-csi-controller-sa"
      }
    }
  }]
}
TRUSTEOF
                  aws iam create-role \
                    --role-name "$ROLE_NAME" \
                    --assume-role-policy-document file:///tmp/ebs-trust.json
                  aws iam attach-role-policy \
                    --role-name "$ROLE_NAME" \
                    --policy-arn "$EBS_POLICY_ARN"
                  echo "✅ IAM role created and policy attached"
                fi

                ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query Role.Arn --output text)
                echo "Using role: $ROLE_ARN"

                # ── Install EBS CSI addon if missing ───────────────────
                ADDON_STATUS=$(aws eks describe-addon \
                  --cluster-name "$CLUSTER_NAME" \
                  --region "$REGION" \
                  --addon-name aws-ebs-csi-driver \
                  --query addon.status --output text 2>/dev/null || echo "NOT_FOUND")

                if [ "$ADDON_STATUS" = "ACTIVE" ]; then
                  echo "✅ EBS CSI addon already ACTIVE"
                elif [ "$ADDON_STATUS" = "NOT_FOUND" ]; then
                  echo "Installing aws-ebs-csi-driver addon..."
                  aws eks create-addon \
                    --cluster-name "$CLUSTER_NAME" \
                    --region "$REGION" \
                    --addon-name aws-ebs-csi-driver \
                    --service-account-role-arn "$ROLE_ARN" \
                    --resolve-conflicts OVERWRITE
                  echo "Waiting for addon to become ACTIVE..."
                  aws eks wait addon-active \
                    --cluster-name "$CLUSTER_NAME" \
                    --region "$REGION" \
                    --addon-name aws-ebs-csi-driver
                  echo "✅ EBS CSI addon is ACTIVE"
                else
                  echo "Addon is in state: $ADDON_STATUS — updating to ensure correct role..."
                  aws eks update-addon \
                    --cluster-name "$CLUSTER_NAME" \
                    --region "$REGION" \
                    --addon-name aws-ebs-csi-driver \
                    --service-account-role-arn "$ROLE_ARN" \
                    --resolve-conflicts OVERWRITE
                  aws eks wait addon-active \
                    --cluster-name "$CLUSTER_NAME" \
                    --region "$REGION" \
                    --addon-name aws-ebs-csi-driver
                  echo "✅ EBS CSI addon is ACTIVE"
                fi
                '''
            }
        }

        stage('Build Explicit Images') {
            steps {
                script {
                    echo "Building single-platform image for integration tests..."
                    sh 'docker compose -p stressforge build'
                }
            }
        }

        stage('Integration Tests') {
            steps {
                script {
                    echo "Starting containers for testing..."
                    // Automatically assign ephemeral ports to prevent port collisions across concurrent runs.
                    // The testing queries use 'docker exec' connecting to internal 'localhost', which ignores host port bindings.
                    sh 'API_HOST_PORT=0 FRONTEND_HOST_PORT=0 LOCUST_HOST_PORT=0 docker compose -p stressforge up -d'
                    
                    echo "Waiting 30 seconds for services to initialize..."
                    sleep 30
                    
                    echo "Validating API health endpoints..."
                    sh '''
                        API_CONTAINER=$(docker compose -p stressforge ps -q api)
                        if [ -z "$API_CONTAINER" ]; then
                           echo "API container failed to start"
                           exit 1
                        fi
                        
                        docker exec $API_CONTAINER curl -s -f http://localhost:8000/api/health || exit 1
                        docker exec $API_CONTAINER curl -s -f http://localhost:8000/api/health/ready || exit 1
                    '''
                    echo "✅ API Integration tests passed successfully!"
                }
            }
            post {
                always {
                    // Tear down the test environment regardless of success or failure
                    sh 'docker compose -p stressforge down -v'
                }
            }
        }

        stage('Push Multi-Arch Versioned Tags') {
            steps {
                script {
                    echo "Building multi-arch (amd64+arm64) and pushing to Docker Hub..."

                    withCredentials([usernamePassword(credentialsId: 'Docker-hub-ecc', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                        sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'

                        // Create/use a multi-arch buildx builder
                        sh '''
                            docker buildx inspect multiarch-builder > /dev/null 2>&1 \
                                || docker buildx create --name multiarch-builder --driver docker-container --bootstrap
                            docker buildx use multiarch-builder
                        '''

                        def services = [
                            [context: 'backend',  dockerfile: 'backend/Dockerfile',  image: "${API_IMAGE}:${DOCKER_TAG}"],
                            [context: 'frontend', dockerfile: 'frontend/Dockerfile', image: "${FRONTEND_IMAGE}:${DOCKER_TAG}"],
                            [context: '.',        dockerfile: 'worker/Dockerfile',   image: "${WORKER_IMAGE}:${DOCKER_TAG}"],
                            [context: 'locust',   dockerfile: 'locust/Dockerfile',   image: "${LOCUST_IMAGE}:${DOCKER_TAG}"]
                        ]

                        services.each { svc ->
                            retry(2) {
                                sh """set -e
                                    docker buildx build \\
                                        --platform linux/amd64,linux/arm64 \\
                                        --push \\
                                        -t ${svc.image} \\
                                        -f ${svc.dockerfile} \\
                                        ${svc.context}
                                """
                            }
                        }
                    }
                }
            }
        }

        stage('Update Helm Values & Push to Git (GitOps)') {
            steps {
                script {
                    echo "Modifying Helm values.yaml with newly built image tag: ${DOCKER_TAG}"
                    
                    // We use yq to safely update the tags inside the Helm values file.
                    // This creates an auditable commit for ArgoCD.
                    sh """set -e
                        yq e '.image.registry = "${DOCKER_HUB_USER}"' -i helm/stressforge/values.yaml
                        yq e '.image.tags.api = "${DOCKER_TAG}"' -i helm/stressforge/values.yaml
                        yq e '.image.tags.frontend = "${DOCKER_TAG}"' -i helm/stressforge/values.yaml
                        yq e '.image.tags.worker = "${DOCKER_TAG}"' -i helm/stressforge/values.yaml
                        yq e '.image.tags.locust = "${DOCKER_TAG}"' -i helm/stressforge/values.yaml
                    """
                    
                    echo "Committing Helm change to 'staging' branch..."
                    
                    // Uses Jenkins' local SSH or PAT context if cloned securely. 
                    // Set up Jenkins Git config so commits succeed.
                    withCredentials([usernamePassword(credentialsId: 'Github-Ecc', passwordVariable: 'GIT_PAT', usernameVariable: 'GIT_USER')]) {
                        sh '''
                            git config --global user.email "jenkins-ci@stressforge.io"
                            git config --global user.name "Jenkins CI"

                            # Prevent git from hanging waiting for interactive credential prompt
                            export GIT_TERMINAL_PROMPT=0

                            # Embed credentials in remote URL before any network operation
                            git remote set-url origin https://${GIT_USER}:${GIT_PAT}@github.com/atharva0608/load-test-application.git

                            # Safely fetch and checkout staging branch against origin state
                            git fetch origin
                            git checkout staging || git checkout -b staging origin/staging
                            git add helm/stressforge/values.yaml

                            # Only commit if there are changes
                            git diff-index --quiet HEAD || git commit -m "ci: bump helm image tags to build ${DOCKER_TAG}"

                            git push -u origin staging
                        '''
                    }
                }
            }
        }
    }

    post {
        always {
            sh 'docker system prune -f'
        }
        failure {
            echo "❌ Pipeline Failed! Check logs for details."
        }
        success {
            echo "✅ Pipeline Completed! The 'staging' branch is now ready for a PR to 'main' for ArgoCD synchronization."
        }
    }
}
