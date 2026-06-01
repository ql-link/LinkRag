pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    environment {
        IMAGE      = 'tolink-rag'
        TAG        = "${env.GIT_COMMIT?.take(8) ?: env.BUILD_NUMBER}"
        DEPLOY_DIR = '/opt/tolink/toLink-Rag'   // TODO: 本机部署目录，内含 .env 和 deploy/docker-compose.yml
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
                    pip install --upgrade pip -i https://pypi.tuna.tsinghua.edu.cn/simple
                    pip install -e ".[dev]" -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120
                    pytest tests/unit -q
                '''
            }
        }

        stage('Build Image') {
            steps {
                sh "DOCKER_BUILDKIT=1 docker build -t ${IMAGE}:${TAG} -t ${IMAGE}:latest ."
            }
        }

        stage('Deploy') {
            steps {
                sh """
                    cd ${DEPLOY_DIR}
                    export TAG=${TAG}
                    docker compose -f deploy/docker-compose.yml up -d
                """
            }
        }
    }

    post {
        always  { sh 'docker image prune -f || true' }
        success { echo "Deployed ${IMAGE}:${TAG}" }
        failure { echo 'Build failed.' }
    }
}
