pipeline {
    agent any

    environment {
        IMAGE = "mrmonster786/rnr-backend"
        TAG = "${env.BUILD_NUMBER}"
        ALLOWED_BRANCH_1 = "dev"
        ALLOWED_BRANCH_2 = "release"
    }

    options {
        buildDiscarder(logRotator(numToKeepStr: '10'))
        disableConcurrentBuilds()
        timestamps()
    }

    stages {

        stage('Branch Guard') {
            when {
                not {
                    anyOf {
                        branch "${ALLOWED_BRANCH_1}"
                        branch "${ALLOWED_BRANCH_2}"
                    }
                }
            }
            steps {
                echo "Build not allowed for branch: ${env.BRANCH_NAME}"
                script {
                    currentBuild.result = 'NOT_BUILT'
                    error("Skipping branch")
                }
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

        stage('Install Dependencies') {
            steps {
                sh '''
                python3 -m venv venv
                . venv/bin/activate
                pip install --upgrade pip
                pip install -r requirements.txt
                '''
            }
        }

        stage('Unit Tests') {
            steps {
                sh '''
                . venv/bin/activate
                pytest --maxfail=1 --disable-warnings
                '''
            }
        }

        stage('SAST - Bandit') {
            steps {
                sh '''
                . venv/bin/activate
                bandit -r . -f json -o bandit-report.json
                '''
            }
        }

        stage('Dependency Scan - pip-audit') {
            steps {
                sh '''
                . venv/bin/activate
                pip-audit --format json --output pip-audit-report.json
                '''
            }
        }

        stage('Build Docker Image') {
            steps {
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

        stage('Deploy to Dev') {
            when {
                branch 'dev'
            }
            steps {
                sh './deploy.sh dev $TAG'
            }
        }

        stage('Deploy to Staging') {
            when {
                branch 'release'
            }
            steps {
                sh './deploy.sh staging $TAG'
            }
        }

        stage('DAST - OWASP ZAP (Release Only)') {
            when {
                branch 'release'
            }
            steps {
                sh '''
                docker run --rm -t owasp/zap2docker-stable \
                  zap-baseline.py \
                  -t http://staging.yourdomain.com \
                  -r zap-report.html
                '''
            }
        }

        stage('Manual Approval for Production') {
            when {
                branch 'release'
            }
            steps {
                input message: "Promote this release to production?", ok: "Deploy"
            }
        }

        stage('Deploy to Production') {
            when {
                branch 'release'
            }
            steps {
                sh './deploy.sh production $TAG'
            }
        }
    }

    post {

        always {
            archiveArtifacts artifacts: '*.json, *.html', allowEmptyArchive: true
            cleanWs()
        }

        failure {
            echo "Build failed due to security or test issue."
        }

        success {
            echo "Secure build completed successfully."
        }

    }
}