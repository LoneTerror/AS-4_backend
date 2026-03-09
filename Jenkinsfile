pipeline {
    agent any

    environment {
        IMAGE = "mrmonster786/rnr-backend"
        TAG = "${env.BUILD_NUMBER}"
        TARGET_EC2_HOST="test.aabhar.top"
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
                                string(credentialsId: 'rr-backend-redis-url',variable: 'REDIS_URL'),
                                string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                                string(credentialsId: 'rr-backend-algorithm', variable: 'ALGORITHM'),
                                string(credentialsId: 'rr-backend-smtp-password', variable: 'SMTP_PASSWORD'),
                                string(credentialsId: 'rr-backend-smtp-username', variable: 'SMTP_USERNAME'),
                                string(credentialsId: 'rr-backend-smtp-from-email', variable: 'SMTP_FROM_EMAIL'),
                                string(credentialsId: 'rr-backend-auth-service-url', variable: 'AUTH_SERVICE_URL'),
                                string(credentialsId: 'rr-backend-slack-bot-token', variable: 'SLACK_BOT_TOKEN'),
                                string(credentialsId: 'rr-backend-cors-origins', variable: 'FRONTEND_CORS_ORIGINS'),
                                string(credentialsId: 'rr-backend-frontend-url', variable: 'FRONTEND_URL'),
                                string(credentialsId: 'rr-backend-slack-default-channel-id', variable: 'SLACK_DEFAULT_CHANNEL_ID'),
                                ]) {
                                    try {
                                        sh """
                                        docker run -d \
                                        --name target-app \
                                        --network zap-net \
                                        -e DATABASE_URL="${DATABASE_URL}" \
                                        -e REDIS_URL="${REDIS_URL}" \
                                        -e SECRET_KEY="${SECRET_KEY}" \
                                        -e ALGORITHM="${ALGORITHM}" \
                                        -e AUTH_SERVICE_URL="${AUTH_SERVICE_URL}" \
                                        -e SLACK_BOT_TOKEN="${SLACK_BOT_TOKEN}" \
                                        -e SLACK_DEFAULT_CHANNEL_ID="${SLACK_DEFAULT_CHANNEL_ID}" \
                                        -e SMTP_PASSWORD="${SMTP_PASSWORD}" \
                                        -e SMTP_USERNAME="${SMTP_USERNAME}" \
                                        -e SMTP_HOST="smtp.gmail.com" \
                                        -e SMTP_PORT="587" \
                                        -e SMTP_FROM_EMAIL="${SMTP_FROM_EMAIL}"\
                                        -e SMTP_USE_TLS="true" \
                                        -e SMTP_USE_SSL="false" \
                                        -e FRONTEND_URL="${FRONTEND_URL}" \
                                        -e FRONTEND_CORS_ORIGINS="${FRONTEND_CORS_ORIGINS}" \
                                        -e ACCESS_TOKEN_EXPIRE_MINUTES="30" \
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

        stage('Push Image') {
            when { branch 'pipeline-branch' }
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
        

        stage('Deploy to EC2 (AWS)') {
            when { branch 'pipeline-branch' } 
            steps {
                script {
                    sshagent(credentials: ['ec2-ssh-key']) {
                        withCredentials([
                            string(credentialsId: 'rr-backend-db-url', variable: 'DATABASE_URL'),
                            string(credentialsId: 'rr-backend-redis-url',variable: 'REDIS_URL'),
                            string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                            string(credentialsId: 'rr-backend-smtp-password', variable: 'SMTP_PASSWORD'),
                            string(credentialsId: 'rr-backend-smtp-from-email', variable: 'SMTP_FROM_EMAIL'),
                            string(credentialsId: 'rr-backend-smtp-username', variable: 'SMTP_USERNAME'),
                            string(credentialsId: 'rr-backend-auth-service-url', variable: 'AUTH_SERVICE_URL'),
                            string(credentialsId: 'rr-backend-slack-bot-token', variable: 'SLACK_BOT_TOKEN'),
                            string(credentialsId: 'rr-backend-slack-default-channel-id', variable: 'SLACK_DEFAULT_CHANNEL_ID'),
                            string(credentialsId: 'rr-backend-cors-origins', variable: 'FRONTEND_CORS_ORIGINS'),
                            string(credentialsId: 'rr-backend-frontend-url', variable: 'FRONTEND_URL')
                        ]) {
                            sh """
                            ssh -o StrictHostKeyChecking=no ubuntu@${TARGET_EC2_HOST} "
                                docker stop rnr-backend-test || true
                                docker rm rnr-backend-test || true
                                
                                # Pull the latest image if you are pushing to a registry like Docker Hub
                                # docker pull ${IMAGE}:${TAG} 
                                
                                docker run -d \\
                                --name rnr-backend-test \\
                                --restart always \\
                                --add-host host.docker.internal:host-gateway \\
                                -p 8000:8000 \\
                                -e DATABASE_URL='${DATABASE_URL}' \\
                                -e REDIS_URL='${REDIS_URL}' \\
                                -e SECRET_KEY='${SECRET_KEY}' \\
                                -e AUTH_SERVICE_URL='${AUTH_SERVICE_URL}' \\
                                -e SLACK_BOT_TOKEN='${SLACK_BOT_TOKEN}' \\
                                -e SLACK_DEFAULT_CHANNEL_ID='${SLACK_DEFAULT_CHANNEL_ID}' \\
                                -e SMTP_PASSWORD='${SMTP_PASSWORD}' \\
                                -e SMTP_USERNAME='${SMTP_USERNAME}' \\
                                -e SMTP_HOST='smtp.gmail.com' \\
                                -e SMTP_PORT='587' \\
                                -e SMTP_FROM_EMAIL='${SMTP_FROM_EMAIL}' \\
                                -e SMTP_USE_TLS='true' \\
                                -e SMTP_USE_SSL='false' \\
                                -e FRONTEND_URL='${FRONTEND_URL}' \\
                                -e ACCESS_TOKEN_EXPIRE_MINUTES='30' \\
                                -e OTEL_SERVICE_NAME='rnr-backend' \\
                                -e OTEL_EXPORTER_OTLP_ENDPOINT='http://host.docker.internal:4317' \\
                                -e FRONTEND_CORS_ORIGINS='${FRONTEND_CORS_ORIGINS}' \\
                                ${IMAGE}:${TAG}

                                echo '🧹 Running DevSecOps cleanup: Removing old containers and images...'
                                docker system prune -f
                                docker image prune -af --filter 'until=24h'
                            "
                            """
                        }
                    }
                    echo "🚀 Application deployed successfully. Traffic handled by Nginx." 
                    // Active Health Check Observation via the secure domain
                    echo "⏳ Waiting for staggered services to boot..."
                    timeout(time: 3, unit: 'MINUTES') { 
                        waitUntil {
                            script {
                                // Pinging through the public Nginx gateway instead of localhost
                                def r = sh(script: "curl -s -o /dev/null -w '%{http_code}' https://${TARGET_EC2_HOST}/v1/auth/health || true", returnStdout: true).trim()
                                if (r != "200") {
                                    echo "Still waiting for Auth Service... HTTP Code: ${r}"
                                }
                                return (r == "200")
                            }
                        }
                    }
                    echo "✅ Application is fully booted and responding!"
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
        }
        success {
            withCredentials([
                string(credentialsId: 'rr-backend-slack-bot-token', variable: 'SLACK_TOKEN'),
                string(credentialsId: 'rr-backend-slack-default-channel-id', variable: 'SLACK_CHANNEL')
            ]) {
                sh """
                curl -X POST -H 'Authorization: Bearer ${SLACK_TOKEN}' \
                -H 'Content-type: application/json' \
                --data '{
                    "channel":"${SLACK_CHANNEL}",
                    "text":"✅ *Success*: Build #${env.BUILD_NUMBER} of rnr-backend deployed to AWS successfully.\\n🔍 <${env.BUILD_URL}|View Jenkins Logs> | 📊 <https://${env.TARGET_EC2_HOST}/jaeger/|View Live Traces in Jaeger>"
                }' \
                https://slack.com/api/chat.postMessage
                """
            }
        }
        failure {
            withCredentials([
                string(credentialsId: 'rr-backend-slack-bot-token', variable: 'SLACK_TOKEN'),
                string(credentialsId: 'rr-backend-slack-default-channel-id', variable: 'SLACK_CHANNEL')
            ]) {
                sh """
                curl -X POST -H 'Authorization: Bearer ${SLACK_TOKEN}' \
                -H 'Content-type: application/json' \
                --data '{
                    "channel":"${SLACK_CHANNEL}",
                    "text":"❌ *Failure*: Build #${env.BUILD_NUMBER} of rnr-backend failed.\\n🔍 <${env.BUILD_URL}|Check Jenkins Logs immediately>"
                }' \
                https://slack.com/api/chat.postMessage
                """
            }
        }
    }
}