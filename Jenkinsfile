pipeline {
    agent any

    environment {
        // Core configuration
        DOCKER_HUB_USER = 'atharvapudale'
        APP_NAME = 'stressforge'
        // STRICT GIT-OPS: We only use the deterministic Jenkins BUILD_NUMBER as our tag. 
        // No 'latest' tags are pushed to avoid untraceable config drift.
        DOCKER_TAG = "${env.BUILD_NUMBER}"
        
        // Explicitly defined image names
        API_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-api"
        FRONTEND_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-frontend"
        WORKER_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-worker"
        LOCUST_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-locust"
    }

    stages {
        stage('Checkout') {
            steps {
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
                # Install Docker Compose v2
                # ----------------------------
                if ! docker compose version >/dev/null 2>&1; then
                  echo "Installing Docker Compose plugin..."
                  mkdir -p /usr/libexec/docker/cli-plugins
                  curl -SL https://github.com/docker/compose/releases/latest/download/docker-compose-linux-x86_64 \
                    -o /usr/libexec/docker/cli-plugins/docker-compose
                  chmod +x /usr/libexec/docker/cli-plugins/docker-compose
                fi

                # ----------------------------
                # Install yq
                # ----------------------------
                if ! command -v yq >/dev/null 2>&1; then
                  echo "Installing yq..."
                  curl -SL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_amd64 \
                    -o /usr/local/bin/yq
                  chmod +x /usr/local/bin/yq
                fi

                echo "✅ All tools ready"

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

        stage('Build Explicit Images') {
            steps {
                script {
                    echo "Building images with fixed project name to avoid fragile directory dependency..."
                    // Fixing fragile directory prefix by explicitly forcing the Compose project name
                    sh 'docker compose -p stressforge build'
                }
            }
        }

        stage('Integration Tests') {
            steps {
                script {
                    echo "Starting containers for testing..."
                    // Run explicitly named project
                    sh 'docker compose -p stressforge up -d'
                    
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

        stage('Push Versioned Tags Only') {
            steps {
                script {
                    echo "Tagging and pushing images to Docker Hub (STRICT VERSION TAGS ONLY)..."
                    
                    withCredentials([usernamePassword(credentialsId: 'Docker-hub-ecc', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                        sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                        
                        // We use the enforced prefix "stressforge" instead of relying on default folder names
                        def prefix = "stressforge"
                        
                        // ONLY push DOCKER_TAG. No :latest tag ever gets pushed from CI in GitOps mode!
                        retry(2) {
                            sh """set -e
                                docker tag ${prefix}-api:latest ${API_IMAGE}:${DOCKER_TAG}
                                docker push ${API_IMAGE}:${DOCKER_TAG}
                                
                                docker tag ${prefix}-frontend:latest ${FRONTEND_IMAGE}:${DOCKER_TAG}
                                docker push ${FRONTEND_IMAGE}:${DOCKER_TAG}
                                
                                docker tag ${prefix}-worker:latest ${WORKER_IMAGE}:${DOCKER_TAG}
                                docker push ${WORKER_IMAGE}:${DOCKER_TAG}
                                
                                docker tag ${prefix}-locust:latest ${LOCUST_IMAGE}:${DOCKER_TAG}
                                docker push ${LOCUST_IMAGE}:${DOCKER_TAG}
                            """
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
                            
                            # Safely fetch and checkout staging branch against origin state
                            git fetch origin
                            git checkout staging || git checkout -b staging origin/staging
                            git add helm/stressforge/values.yaml
                            
                            # Only commit if there are changes
                            git diff-index --quiet HEAD || git commit -m "ci: bump helm image tags to build ${DOCKER_TAG}"
                            
                            # Push using the credentials
                            git remote set-url origin https://${GIT_USER}:${GIT_PAT}@github.com/atharva0608/load-test-application.git
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
