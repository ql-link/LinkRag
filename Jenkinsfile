pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        REGISTRY    = 'registry.example.com/tolink'   // TODO: 改成你的镜像仓库
        IMAGE_NAME  = 'tolink-rag'
        IMAGE       = "${REGISTRY}/${IMAGE_NAME}"
        TAG         = "${env.GIT_COMMIT?.take(8) ?: env.BUILD_NUMBER}"
        DEPLOY_HOST = 'deploy@your-server'             // TODO: 部署目标主机
        DEPLOY_DIR  = '/opt/tolink/toLink-Rag'
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Test') {
            agent {
                docker { image 'python:3.11-slim'; reuseNode true }
            }
            steps {
                sh '''
                    pip install --upgrade pip
                    pip install -e ".[dev]"
                    pytest tests/unit -q
                '''
            }
        }

        stage('Build Image') {
            steps {
                sh "DOCKER_BUILDKIT=1 docker build -t ${IMAGE}:${TAG} -t ${IMAGE}:latest ."
            }
        }

        stage('Push Image') {
            steps {
                withCredentials([usernamePassword(credentialsId: 'registry-cred',
                        usernameVariable: 'REG_USER', passwordVariable: 'REG_PASS')]) {
                    sh '''
                        echo "$REG_PASS" | docker login ${REGISTRY%%/*} -u "$REG_USER" --password-stdin
                        docker push ${IMAGE}:${TAG}
                        docker push ${IMAGE}:latest
                    '''
                }
            }
        }

        stage('Deploy') {
            steps {
                sshagent(credentials: ['deploy-ssh-key']) {
                    sh """
                        ssh -o StrictHostKeyChecking=no ${DEPLOY_HOST} '
                            cd ${DEPLOY_DIR} &&
                            export REGISTRY=${REGISTRY} TAG=${TAG} &&
                            docker compose -f deploy/docker-compose.yml pull &&
                            docker compose -f deploy/docker-compose.yml up -d
                        '
                    """
                }
            }
        }
    }

    post {
        always  { sh 'docker image prune -f || true' }
        success { echo "Deployed ${IMAGE}:${TAG}" }
        failure { echo 'Build failed.' }
    }
}
