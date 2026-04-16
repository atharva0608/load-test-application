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
                git branch: 'main', credentialsId: 'Github-Ecc', url: 'https://github.com/atharva0608/load-test-application.git'
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
                        sh "docker tag ${prefix}-api:latest ${API_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${API_IMAGE}:${DOCKER_TAG}"
                        
                        sh "docker tag ${prefix}-frontend:latest ${FRONTEND_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${FRONTEND_IMAGE}:${DOCKER_TAG}"
                        
                        sh "docker tag ${prefix}-worker:latest ${WORKER_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${WORKER_IMAGE}:${DOCKER_TAG}"
                        
                        sh "docker tag ${prefix}-locust:latest ${LOCUST_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${LOCUST_IMAGE}:${DOCKER_TAG}"
                    }
                }
            }
        }

        stage('Update Helm Values & Push to Git (GitOps)') {
            steps {
                script {
                    echo "Modifying Helm values.yaml with newly built image tag: ${DOCKER_TAG}"
                    
                    // We use basic sed substitution to update the tags inside the Helm values file.
                    // This creates an auditable commit for ArgoCD.
                    sh """
                        sed -i.bak 's/api: ".*"/api: "${DOCKER_TAG}"/' helm/stressforge/values.yaml
                        sed -i.bak 's/frontend: ".*"/frontend: "${DOCKER_TAG}"/' helm/stressforge/values.yaml
                        sed -i.bak 's/worker: ".*"/worker: "${DOCKER_TAG}"/' helm/stressforge/values.yaml
                        sed -i.bak 's/locust: ".*"/locust: "${DOCKER_TAG}"/' helm/stressforge/values.yaml
                        rm -f helm/stressforge/values.yaml.bak
                    """
                    
                    echo "Committing Helm change to 'staging' branch..."
                    
                    // Uses Jenkins' local SSH or PAT context if cloned securely. 
                    // Set up Jenkins Git config so commits succeed.
                    withCredentials([usernamePassword(credentialsId: 'Github-Ecc', passwordVariable: 'GIT_PAT', usernameVariable: 'GIT_USER')]) {
                        sh '''
                            git config --global user.email "jenkins-ci@stressforge.io"
                            git config --global user.name "Jenkins CI"
                            
                            # Safely checkout staging branch without overwriting changes
                            git checkout staging || git checkout -b staging
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
        failure {
            echo "❌ Pipeline Failed! Check logs for details."
        }
        success {
            echo "✅ Pipeline Completed! The 'staging' branch is now ready for a PR to 'main' for ArgoCD synchronization."
        }
    }
}
