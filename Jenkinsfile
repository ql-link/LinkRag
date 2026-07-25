pipeline {
    agent any

    options {
        timestamps()
        disableConcurrentBuilds()
        buildDiscarder(logRotator(numToKeepStr: '20'))
    }

    parameters {
        booleanParam(name: 'RUN_TESTS', defaultValue: false, description: '是否执行 Test 阶段；默认跳过以加快构建')
    }

    environment {
        IMAGE      = 'tolink-rag'
        TAG        = "${env.GIT_COMMIT?.take(8) ?: env.BUILD_NUMBER}"
        DEPLOY_DIR = '/opt/tolink/toLink-Rag'   // 基础配置由 Jenkins 更新，本机密钥文件长期保留
        RAG_ENV_FILE = '/opt/tolink/toLink-Rag/.env.production'
        RAG_SECRET_ENV_FILE = '/opt/tolink/toLink-Rag/.env.production.local'
    }

    stages {
        stage('Checkout') {
            steps { checkout scm }
        }

        stage('Test') {
            when {
                expression { return params.RUN_TESTS }
            }
            agent {
                // 挂载 pip 缓存到 jenkins_home，跨构建复用已下载的包
                docker { image 'python:3.11-slim'; args '-v $HOME/.cache/pip:/root/.cache/pip'; reuseNode true }
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

        stage('Migrate Database') {
            steps {
                sh '''
                    test -f .env.production || { echo "Missing tracked RAG base config: .env.production"; exit 13; }
                    install -d "$DEPLOY_DIR/deploy" "$DEPLOY_DIR/logs"
                    cmp -s .env.production "$RAG_ENV_FILE" || install -m 0644 .env.production "$RAG_ENV_FILE"
                    cmp -s deploy/docker-compose.yml "$DEPLOY_DIR/deploy/docker-compose.yml" || \
                        install -m 0644 deploy/docker-compose.yml "$DEPLOY_DIR/deploy/docker-compose.yml"

                    test -r "$RAG_SECRET_ENV_FILE" || {
                        echo "Missing or unreadable RAG secret env file: $RAG_SECRET_ENV_FILE"
                        exit 14
                    }
                    test "$(stat -c '%a' "$RAG_SECRET_ENV_FILE")" = "600" || {
                        echo "RAG secret env file must use mode 600: $RAG_SECRET_ENV_FILE"
                        exit 15
                    }

                    cd "$DEPLOY_DIR"
                    export TAG RAG_ENV_FILE RAG_SECRET_ENV_FILE
                    docker network inspect tolink-app-net >/dev/null
                    echo "Running Alembic with production config: $RAG_ENV_FILE + $RAG_SECRET_ENV_FILE"
                    docker run --rm \
                        --network tolink-app-net \
                        --env-file "$RAG_ENV_FILE" \
                        --env-file "$RAG_SECRET_ENV_FILE" \
                        -e PYTHONPATH=/app \
                        "$IMAGE:$TAG" \
                        python scripts/release/run_alembic.py \
                            --expected-app-env production \
                            --expected-host tolink-mysql \
                            --expected-port 3306 \
                            --expected-database tolink_rag_db
                '''
            }
        }

        stage('Deploy') {
            steps {
                sh '''
                    cd "$DEPLOY_DIR"
                    export TAG RAG_ENV_FILE RAG_SECRET_ENV_FILE
                    docker compose -f deploy/docker-compose.yml up -d
                '''
            }
        }
    }

    post {
        always  { sh 'docker image prune -f || true' }
        success { echo "Deployed ${IMAGE}:${TAG}" }
        failure { echo 'Build failed.' }
    }
}
