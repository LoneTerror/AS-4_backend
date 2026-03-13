pipeline {
    agent any

    environment {
        IMAGE = "mrmonster786/rnr-backend"
        TAG = "${env.BUILD_NUMBER}"
        TARGET_EC2_HOST="backend.aabhar.top"
    }

    triggers {
        githubPush() 
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
        timestamps()
    }

    stages {
        stage('Static Analysis & Security') {
            parallel {
                stage('Secrets Scan (Gitleaks)') {
                    steps {
                        sh 'gitleaks detect --source . --report-format json --report-path gitleaks-report.json --exit-code 1'
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
                            # 1. Install system dependencies required for Prisma binaries in slim image
                            apt-get update && apt-get install -y --no-install-recommends libatomic1
                            
                            # 2. Setup environment
                            python -m venv venv
                            . venv/bin/activate
                            
                            # 3. Upgrade pip to support --require-hashes accurately
                            pip install --upgrade pip
                            pip install pip-tools
                            
                            # 4. Sync dependencies from the hashed requirements.txt
                            pip-sync requirements.txt
                            
                            # 5. Install tools needed for this specific stage
                            pip install pytest bandit pip-audit

                            # 6. Generate Prisma Client (Matching the Builder Stage in Dockerfile)
                            echo "Generate Prisma Client..."
                            prisma generate

                            echo "🧪 Running Unit Tests..."
                            pytest src/ --disable-warnings --junitxml=test-results.xml
        
                            echo "🔒 Running Static Security Scans..."
                            bandit -r . --exclude ./venv,./tests -lll -iii -f json -o bandit-report.json || true
                            bandit -r . --exclude ./venv,./tests -lll -iii -f html -o bandit-report.html || true
        
                            pip-audit --format json --output pip-audit-report.json || true

                            echo "📂 Listing files for debugging:"
                            ls -lh bandit-report.html pip-audit-report.json test-results.xml
                        '''
                    }
                }
            }
        }

        stage('Build Docker Image') {
            steps { 
                sh 'docker build -t $IMAGE:$TAG .' 
            }
        }

        stage('Dynamic Analysis') {
            parallel {
                stage('Container Scan - Trivy') {
                    steps {
                       sh 'trivy image --scanners vuln --severity HIGH,CRITICAL --exit-code 0 --format json --output trivy-report.json $IMAGE:$TAG'
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
                                        // Use double quotes for shell variable expansion, single quotes for the sh block
                                        sh """
                                        docker run -d --name target-app --network zap-net \
                                        -e DATABASE_URL="$DATABASE_URL" \
                                        -e REDIS_URL="$REDIS_URL" \
                                        -e SECRET_KEY="$SECRET_KEY" \
                                        -e ALGORITHM="$ALGORITHM" \
                                        -e AUTH_SERVICE_URL="$AUTH_SERVICE_URL" \
                                        -e SLACK_BOT_TOKEN="$SLACK_BOT_TOKEN" \
                                        -e SLACK_DEFAULT_CHANNEL_ID="$SLACK_DEFAULT_CHANNEL_ID" \
                                        -e SMTP_PASSWORD="$SMTP_PASSWORD" \
                                        -e SMTP_USERNAME="$SMTP_USERNAME" \
                                        -e SMTP_HOST="smtp.gmail.com" \
                                        -e SMTP_PORT="587" \
                                        -e SMTP_FROM_EMAIL="$SMTP_FROM_EMAIL"\
                                        -e SMTP_USE_TLS="true" \
                                        -e SMTP_USE_SSL="false" \
                                        -e FRONTEND_URL="$FRONTEND_URL" \
                                        -e FRONTEND_CORS_ORIGINS="$FRONTEND_CORS_ORIGINS" \
                                        -e ACCESS_TOKEN_EXPIRE_MINUTES="30" \
                                        ${IMAGE}:${TAG}
                                        """
                                        sh """
                                        docker run --rm --network zap-net alpine sh -c '
                                            for i in \$(seq 1 30); do
                                                nc -z target-app 8000 && exit 0
                                                echo "Waiting for target-app..."
                                                sleep 2
                                            done
                                            exit 1'
                                        """
                                        sh """
                                        docker run --rm --user 0 --network zap-net \
                                          -v \$(pwd):/zap/wrk/:rw \
                                          ghcr.io/zaproxy/zaproxy:stable \
                                          zap-baseline.py -t http://target-app:8000 -r zap-report.html -I
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
                            string(credentialsId: 'rr-backend-algorithm', variable: 'ALGORITHM'),
                            string(credentialsId: 'rr-backend-redis-url',variable: 'REDIS_URL'),
                            string(credentialsId: 'rr-backend-secret-key', variable: 'SECRET_KEY'),
                            string(credentialsId: 'rr-backend-smtp-password', variable: 'SMTP_PASSWORD'),
                            string(credentialsId: 'rr-backend-smtp-from-email', variable: 'SMTP_FROM_EMAIL'),
                            string(credentialsId: 'rr-backend-smtp-username', variable: 'SMTP_USERNAME'),
                            string(credentialsId: 'rr-backend-auth-service-url', variable: 'AUTH_SERVICE_URL'),
                            string(credentialsId: 'rr-backend-slack-bot-token', variable: 'SLACK_TOKEN'), // Fixed variable names to match shell below
                            string(credentialsId: 'rr-backend-slack-default-channel-id', variable: 'SLACK_CHANNEL'),
                            string(credentialsId: 'rr-backend-cors-origins', variable: 'FRONTEND_CORS_ORIGINS'),
                            string(credentialsId: 'rr-backend-frontend-url', variable: 'FRONTEND_URL')
                        ]) {
                            sh """
                            ssh -o StrictHostKeyChecking=no ubuntu@${TARGET_EC2_HOST} "
                                docker stop rnr-backend-test || true
                                docker rm rnr-backend-test || true
                                docker run -d \\
                                --name rnr-backend-test \\
                                --restart always \\
                                --add-host host.docker.internal:host-gateway \\
                                -p 8000:8000 \\
                                -e DATABASE_URL='${DATABASE_URL}' \\
                                -e ALGORITHM='${ALGORITHM}'\\
                                -e REDIS_URL='${REDIS_URL}' \\
                                -e SECRET_KEY='${SECRET_KEY}' \\
                                -e AUTH_SERVICE_URL='${AUTH_SERVICE_URL}' \\
                                -e SLACK_BOT_TOKEN='${SLACK_TOKEN}' \\
                                -e SLACK_DEFAULT_CHANNEL_ID='${SLACK_CHANNEL}' \\
                                -e SMTP_PASSWORD='${SMTP_PASSWORD}' \\
                                -e SMTP_USERNAME='${SMTP_USERNAME}' \\
                                -e SMTP_HOST='smtp.gmail.com' \\
                                -e SMTP_PORT='587' \\
                                -e SMTP_FROM_EMAIL='${SMTP_FROM_EMAIL}' \\
                                -e SMTP_USE_TLS='true' \\
                                -e SMTP_USE_SSL='false' \\
                                -e FRONTEND_URL='${FRONTEND_URL}' \\
                                -e ACCESS_TOKEN_EXPIRE_MINUTES='30' \\
                                -e FRONTEND_CORS_ORIGINS='${FRONTEND_CORS_ORIGINS}' \\
                                ${IMAGE}:${TAG}
                                
                                docker system prune -f
                            "
                            """
                        }
                    }
                    // Wait for staggered boot
                    timeout(time: 3, unit: 'MINUTES') { 
                        waitUntil {
                            script {
                                def r = sh(script: "curl -s -o /dev/null -w '%{http_code}' https://${TARGET_EC2_HOST}/v1/auth/health || true", returnStdout: true).trim()
                                return (r == "200")
                            }
                        }
                    }
                }
            }
        }
    }

    post {
        always {
            archiveArtifacts artifacts: '**/bandit-report.json, **/bandit-report.html, **/zap-report.html, **/test-results.xml, **/pip-audit-report.json', allowEmptyArchive: true
            junit testResults: '**/test-results.xml', allowEmptyResults: true
            publishHTML([
                allowMissing: true,
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
                sh '''
                curl -s -X POST https://slack.com/api/chat.postMessage \
                -H "Authorization: Bearer $SLACK_TOKEN" \
                -H "Content-type: application/json" \
                -d @- <<EOF
                {
                    "channel": "$SLACK_CHANNEL",
                    "text": "✅ *Success*: Build #$BUILD_NUMBER of rnr-backend deployed successfully.\\n🔍 <$BUILD_URL|Logs>"
                }
EOF
                '''
            }
        }
        failure {
            withCredentials([
                string(credentialsId: 'rr-backend-slack-bot-token', variable: 'SLACK_TOKEN'),
                string(credentialsId: 'rr-backend-slack-default-channel-id', variable: 'SLACK_CHANNEL')
            ]) {
                sh '''
                curl -s -X POST https://slack.com/api/chat.postMessage \
                -H "Authorization: Bearer $SLACK_TOKEN" \
                -H "Content-type: application/json" \
                -d @- <<EOF
                {
                    "channel": "$SLACK_CHANNEL",
                    "text": "❌ *Failure*: Build #$BUILD_NUMBER failed.\\n🔍 <$BUILD_URL|Check Logs>"
                }
EOF
                '''
            }
        }
    }
}