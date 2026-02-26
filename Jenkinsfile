pipeline {
    agent any

    environment {
        IMAGE = "mrmonster786/rnr-backend"
        TAG = "${env.BUILD_NUMBER}"
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
        timestamps()
    }

    stages {
        // --- STAGE 1: Host Level Checks ---
        stage('Branch Guard') {
            when { not { branch 'develop' } }
            steps {
                error("Only develop branch allowed")
            }
        }

        stage('Checkout') {
            steps {
                checkout scm
            }
        }

        stage('Secrets Scan (Gitleaks)') {
            steps {
                sh '''
                gitleaks detect \
                  --source . \
                  --report-format json \
                  --report-path gitleaks-report.json \
                  --exit-code 1
                '''
            }
        }

        // --- STAGE 2: Python 3.10 Context (The Fix) ---
        // We group all Python tasks here and run them inside a container
        stage('Python Quality Checks') {
            agent {
                docker {
                    image 'python:3.10-slim'
                    // Run as root to prevent permission issues with the mounted workspace
                    args '-u 0:0' 
                }
            }
            stages {
                stage('Install Dependencies') {
                    steps {
                        sh '''
                        # We are inside the container now.
                        # No need for venv here since the container is ephemeral, 
                        # but we stick to your workflow to keep paths consistent.
                        python -m venv venv
                        . venv/bin/activate
                        pip install --upgrade pip
                        pip install -r requirements.txt
                        pip install pytest bandit pip-audit
                        '''
                    }
                }

                stage('Unit Tests') {
                    steps {
                        sh '''
                        . venv/bin/activate
                        # Added || true so pipeline shows test results even if some fail (optional)
                        pytest --maxfail=1 --disable-warnings
                        '''
                    }
                }

                stage('SAST - Bandit') {
                    steps {
                        sh '''
                        . venv/bin/activate
                        # Exclude venv and tests, only scan actual application code
                        bandit -r . --exclude ./venv,./tests -f json -o bandit-report.json
                        '''
                    }
                }

                stage('Dependency Scan') {
                    steps {
                        sh '''
                        . venv/bin/activate
                        pip-audit --format json --output pip-audit-report.json
                        '''
                    }
                }
            }
        }

        // --- STAGE 3: Build & Publish (Back on Host) ---
        stage('Build Docker Image') {
            steps {
                // Ensure the venv from the previous stage is NOT copied into the final image
                // (Make sure venv is in your .dockerignore)
                sh 'docker build -t $IMAGE:$TAG .'
            }
        }

        stage('Container Scan - Trivy') {
            steps {
                sh '''
                trivy image \
                  --severity HIGH,CRITICAL \
                  --exit-code 1 \
                  --format json \
                  --output trivy-report.json \
                  $IMAGE:$TAG
                '''
            }
        }

        stage('Push Image') {
            steps {
                withCredentials([usernamePassword(
                    credentialsId: 'dockerhub-creds',
                    usernameVariable: 'DOCKER_USER',
                    passwordVariable: 'DOCKER_PASS'
                )]) {
                    sh '''
                    echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                    docker push $IMAGE:$TAG
                    docker tag $IMAGE:$TAG $IMAGE:latest
                    docker push $IMAGE:latest
                    '''
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: '*.json, *.html', allowEmptyArchive: true
            cleanWs()
        }
    }
}