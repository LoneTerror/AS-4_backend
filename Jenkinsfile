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
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Secrets Scan (Gitleaks)') {
            steps {
                // Gitleaks doesn't have a native HTML output, so we archive the JSON
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
            stages {
                stage('Install Dependencies') {
                    steps {
                        sh '''
                        python -m venv venv
                        . venv/bin/activate
                        pip install --upgrade pip
                        pip install -r requirements.txt
                        pip install pytest bandit pip-audit
                        '''
                    }
                }

                stage('SAST - Bandit') {
                    steps {
                        sh '''
                        . venv/bin/activate
                        # Generate HTML for the dashboard and JSON for raw data
                        bandit -r . --exclude ./venv,./tests -lll -iii -f json -o bandit-report.json
                        bandit -r . --exclude ./venv,./tests -lll -iii -f html -o bandit-report.html || true
                        '''
                    }
                }

                stage('Dependency Scan') {
                    steps {
                        sh '''
                        . venv/bin/activate
                        # pip-audit focuses on JSON/Text; we will archive these
                        pip-audit --format json --output pip-audit-report.json || true
                        '''
                    }
                }
            }
        }

        stage('Build Docker Image') {
            steps { sh 'docker build -t $IMAGE:$TAG .' }
        }

        stage('Container Scan - Trivy') {
            steps {
                sh '''
                # Fixed: Changed format to 'table' for console visibility, 
                # keep json for the Security Dashboard.
                trivy image --scanners vuln --severity HIGH,CRITICAL --format json --output trivy-report.json $IMAGE:$TAG || true
                '''
            }
        }

        stage('DAST - OWASP ZAP') {
            steps {
                script {
                    sh 'docker network create zap-net || true'
                    withCredentials([
                        string(credentialsId: 'rr-backend-db-url', variable: 'DB_URL'),
                        string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                        string(credentialsId: 'rr-backend-algorithm', variable: 'ALGO')
                    ]) {
                        try {
                            sh "docker run -d --name target-app --network zap-net -e DATABASE_URL='${DB_URL}' -e SECRET_KEY='${SECRET_KEY}' -e ALGORITHM='${ALGO}' ${IMAGE}:${TAG}"
                            sh 'sleep 15' 
                            // ZAP generates a very detailed HTML report by default with the -r flag
                            sh "docker run --rm --user 0 --network zap-net -v \$(pwd):/zap/wrk/:rw ghcr.io/zaproxy/zaproxy:stable zap-baseline.py -t http://target-app:8000 -r zap-report.html || true"
                        } finally {
                            sh 'docker stop target-app && docker rm target-app || true'
                            sh 'docker network rm zap-net || true'
                        }
                    }
                }
            }
        }

        stage('Push Image') {
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

        stage('Deploy to VM1 (Testing)') {
            when { branch 'pipeline-branch' } 
            steps {
                script {
                    sh "docker stop rnr-backend-test || true"
                    sh "docker rm rnr-backend-test || true"
                    
                    withCredentials([
                        string(credentialsId: 'rr-backend-db-url', variable: 'DB_URL'),
                        string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                        string(credentialsId: 'rr-backend-algorithm', variable: 'ALGO')
                    ]) {
                        sh """
                        docker run -d \
                            --name rnr-backend-test \
                            --restart always \
                            -p 8000:8000 \
                            -e DATABASE_URL="${DB_URL}" \
                            -e SECRET_KEY="${SECRET_KEY}" \
                            -e ALGORITHM="${ALGO}" \
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
            // 1. Archive everything for historical records 
            archiveArtifacts artifacts: '**/*.json, **/*.html', allowEmptyArchive: true
            
            // 2. Publish to the sidebar "Security Dashboard"
            publishHTML([
                allowMissing: false,
                alwaysLinkToLastBuild: true,
                keepAll: true,
                reportDir: '.',
                reportFiles: 'bandit-report.html, trivy-report.html, zap-report.html',
                reportName: 'Security Dashboard',
                reportTitles: 'Bandit (SAST), Trivy (Container), OWASP ZAP (DAST)'
            ])
            
            // cleanWs() 
            // sh "docker rmi ${IMAGE}:${TAG} || true" 
        }
        failure {
            sh "docker system prune -f" 
        }
    }
}