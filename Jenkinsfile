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
        // 1. Parallelize Static Scans (Gitleaks + Python Audit)
        stage('Static Analysis & Security') {
            parallel {
                stage('Secrets Scan (Gitleaks)') {
                    steps {
                        sh 'gitleaks detect --source . --report-format json --report-path gitleaks-report.json --exit-code 0'
                    }
                }

                stage('Python Quality Checks') {
                    agent {
                        docker {
                            image 'python:3.10-slim'
                            args '-u 0:0' 
                        }
                    }
                    steps {
                        sh '''
                        python -m venv venv
                        . venv/bin/activate
                        pip install --upgrade pip
                        pip install bandit pip-audit
                        
                        # Running Bandit and Pip-Audit in background to save time
                        bandit -r . --exclude ./venv,./tests -lll -iii -f json -o bandit-report.json &
                        bandit -r . --exclude ./venv,./tests -lll -iii -f html -o bandit-report.html &
                        pip-audit --format json --output pip-audit-report.json &
                        wait
                        '''
                    }
                }
            }
        }

        // 2. Build Stage (Now uses Multi-Stage Dockerfile with Node.js pre-installed)
        stage('Build Docker Image') {
            steps { 
                sh 'docker build -t $IMAGE:$TAG .' 
            }
        }

        // 3. Parallelize Container Scan and DAST
        stage('Dynamic Analysis') {
            parallel {
                stage('Container Scan - Trivy') {
                    steps {
                        sh 'trivy image --scanners vuln --severity HIGH,CRITICAL --format json --output trivy-report.json $IMAGE:$TAG || true'
                    }
                }

                stage('DAST - OWASP ZAP') {
                    steps {
                        script {
                            sh 'docker network create zap-net || true'
                            withCredentials([
                                string(credentialsId: 'rr-backend-db-url', variable: 'DATABASE_URL'),
                                string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                                string(credentialsId: 'rr-backend-algorithm', variable: 'ALGORITHM'),
                                string(credentialsId: 'rr-backend-smtp-password', variable: 'SMTP_PASSWORD'),
                                string(credentialsId: 'rr-backend-smtp-username', variable: 'SMTP_USERNAME')
                                ]) {
                                    try {
                                        sh """
                                        docker run -d \
                                        --name target-app \
                                        --network zap-net \
                                        -e DATABASE_URL="${DATABASE_URL}" \
                                        -e SECRET_KEY="${SECRET_KEY}" \
                                        -e ALGORITHM="${ALGORITHM}" \
                                        ${IMAGE}:${TAG}
                                        """
                                        sh 'sleep 10'
                                        sh """
                                        docker run --rm --user 0 --network zap-net \
                                        -v \$(pwd):/zap/wrk/:rw \
                                        ghcr.io/zaproxy/zaproxy:stable \
                                        zap-baseline.py -t http://target-app:8000 -r zap-report.html || true
                                        """
                                    } finally {
                                        sh 'docker stop target-app || true'
                                        sh 'docker rm target-app || true'
                                        sh 'docker network rm zap-net || true'
                                    }
                                }
                        }
                    }
                }
            }
        }

        /* stage('Push Image') {
            when { branch 'develop' }
            steps {
                withCredentials([usernamePassword(credentialsId: 'dockerhub-creds', usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                    sh '''
                    echo $DOCKER_PASS | docker login -u $DOCKER_USER --password-stdin
                    docker push $IMAGE:$TAG
                    docker tag $IMAGE:$TAG $IMAGE:latest
                    docker push $IMAGE:latest
                    '''
                }
            }
        } 
        */

        stage('Deploy to VM1 (Testing)') {
            when { branch 'pipeline-branch' } 
            steps {
                script {
                    sh "docker stop rnr-backend-test || true"
                    sh "docker rm rnr-backend-test || true"
                    
                    withCredentials([
                        string(credentialsId: 'rr-backend-db-url', variable: 'DATABASE_URL'),
                        string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                        string(credentialsId: 'rr-backend-smtp-password', variable: 'SMTP_PASSWORD'),
                        string(credentialsId: 'rr-backend-smtp-username', variable: 'SMTP_USERNAME')
                    ]) {
                        sh """
                        docker run -d \
                        --name rnr-backend-test \
                        --restart always \
                        -p 8000:8000 \
                        -e DATABASE_URL="${DATABASE_URL}" \
                        -e SECRET_KEY="${SECRET_KEY}" \
                        -e SMTP_PASSWORD="${SMTP_PASSWORD}" \
                        -e SMTP_USERNAME="${SMTP_USERNAME}" \
                        -e SMTP_HOST="smtp.gmail.com" \
                        -e SMTP_PORT="587" \
                        -e SMTP_USE_TLS="true" \
                        -e SMTP_USE_SSL="false" \
                        -e FRONTEND_URL="https://localhost:3000" \
                        -e ACCESS_TOKEN_EXPIRE_MINUTES="30" \
                        ${IMAGE}:${TAG}
                        """
                    }
                    echo "🚀 Application deployed to http://192.168.116.137:8000" 
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: '**/*.json, **/*.html', allowEmptyArchive: true
            
            publishHTML([
                allowMissing: false,
                alwaysLinkToLastBuild: true,
                keepAll: true,
                reportDir: '.',
                reportFiles: 'bandit-report.html, zap-report.html',
                reportName: 'Security Dashboard',
                reportTitles: 'Bandit (SAST), OWASP ZAP (DAST)'
            ])
            
            // cleanWs() 
            // sh "docker rmi ${IMAGE}:${TAG} || true" 
        }
        failure {
            // Keep the system clean on failure without losing build cache
            sh "docker ps -q -f name=target-app | xargs -r docker stop"
        }
    }
}