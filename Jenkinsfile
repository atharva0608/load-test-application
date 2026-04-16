pipeline {
    agent any

    environment {
        // Environment variables for building and pushing images
        DOCKER_HUB_USER = 'atharvapudale' // Change this to your actual Docker Hub username if different
        APP_NAME = 'stressforge'
        DOCKER_TAG = "${env.BUILD_NUMBER}"
        
        // Image names
        API_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-api"
        FRONTEND_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-frontend"
        WORKER_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-worker"
        LOCUST_IMAGE = "${DOCKER_HUB_USER}/${APP_NAME}-locust"
    }

    stages {
        stage('Checkout') {
            steps {
                // Checkout code from Git
                checkout scm
            }
        }

        stage('Build Images') {
            steps {
                script {
                    echo "Building multi-arch Docker images using docker compose..."
                    // Use docker compose to build the stack
                    sh 'docker compose -f docker-compose.yml build'
                }
            }
        }

        stage('Integration Tests') {
            steps {
                script {
                    echo "Starting containers for testing..."
                    // Start the containers locally
                    sh 'docker compose -f docker-compose.yml up -d'
                    
                    // Wait for the API to become ready (the healthcheck takes up to 20-30s to pass initially)
                    echo "Waiting 30 seconds for services to initialize..."
                    sleep 30
                    
                    // Ping the local endpoints to verify functionality.
                    // The API port might have been remapped in docker-compose.yml (e.g. 8001), 
                    // or we can test it from inside the jenkins docker network by exec-ing into another container.
                    echo "Pinging internal API health endpoints..."
                    sh '''
                        # Find the ID of the API container
                        API_CONTAINER=$(docker compose ps -q api)
                        if [ -z "$API_CONTAINER" ]; then
                           echo "API container failed to start"
                           exit 1
                        fi
                        
                        # Test health (FastAPI container internal port is 8000)
                        docker exec $API_CONTAINER curl -s -f http://localhost:8000/api/health || exit 1
                        docker exec $API_CONTAINER curl -s -f http://localhost:8000/api/health/ready || exit 1
                    '''
                    echo "✅ API Integration tests passed successfully!"
                }
            }
            post {
                always {
                    // Tear down the test environment regardless of success or failure
                    sh 'docker compose down -v'
                }
            }
        }

        stage('Push to Docker Hub') {
            steps {
                script {
                    echo "Tagging and pushing images to Docker Hub..."
                    
                    // Assuming Jenkins is configured with Docker Hub credentials ID 'docker-hub-credentials'
                    withCredentials([usernamePassword(credentialsId: 'docker-hub-credentials', passwordVariable: 'DOCKER_PASS', usernameVariable: 'DOCKER_USER')]) {
                        sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                        
                        // Tag previously built docker compose images (which default to foldersname-servicename)
                        // Note: Replace "testapplication" below with your actual folder/project name if docker compose uses a different default prefix
                        def prefix = "testapplication"
                        
                        sh "docker tag ${prefix}-api:latest ${API_IMAGE}:${DOCKER_TAG}"
                        sh "docker tag ${prefix}-api:latest ${API_IMAGE}:latest"
                        sh "docker push ${API_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${API_IMAGE}:latest"
                        
                        sh "docker tag ${prefix}-frontend:latest ${FRONTEND_IMAGE}:${DOCKER_TAG}"
                        sh "docker tag ${prefix}-frontend:latest ${FRONTEND_IMAGE}:latest"
                        sh "docker push ${FRONTEND_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${FRONTEND_IMAGE}:latest"
                        
                        sh "docker tag ${prefix}-worker:latest ${WORKER_IMAGE}:${DOCKER_TAG}"
                        sh "docker tag ${prefix}-worker:latest ${WORKER_IMAGE}:latest"
                        sh "docker push ${WORKER_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${WORKER_IMAGE}:latest"
                        
                        sh "docker tag ${prefix}-locust:latest ${LOCUST_IMAGE}:${DOCKER_TAG}"
                        sh "docker tag ${prefix}-locust:latest ${LOCUST_IMAGE}:latest"
                        sh "docker push ${LOCUST_IMAGE}:${DOCKER_TAG}"
                        sh "docker push ${LOCUST_IMAGE}:latest"
                    }
                }
            }
        }

        stage('Trigger ArgoCD Sync') {
            steps {
                echo '''
                Images pushed to Docker Hub! 
                ArgoCD will automatically pull the 'latest' tags if Image Updater is configured.
                Alternatively, if you use a webhook, ArgoCD applies the cluster changes automatically.
                '''
            }
        }
    }

    post {
        failure {
            echo "Pipeline Failed! Check logs for details."
        }
        success {
            echo "CI/CD Pipeline Completed Successfully."
        }
    }
}
