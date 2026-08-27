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
        CLOUD_HOST = '100.77.31.79'
        CLOUD_USER = 'root'
        CLOUD_SSH_KEY = '/var/jenkins_home/.ssh/cloud_prod'
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    env.COMMIT_SHORT = sh(
                        script: 'git rev-parse --short=8 HEAD',
                        returnStdout: true
                    ).trim()
                }
            }
        }

        stage('Test') {
            when {
                expression { return params.RUN_TESTS }
            }
            agent {
                // 挂载 pip 缓存到 jenkins_home，跨构建复用已下载的包。
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

        stage('Package Commit') {
            steps {
                sh '''
                    set -eu
                    git archive --format=tar.gz --output=linkrag-rag-source.tar.gz HEAD
                '''
            }
        }

        stage('Deploy Production on Cloud') {
            steps {
                sh '''
                    set -eu
                    case "${BUILD_NUMBER}" in
                        ''|*[!0-9]*) echo 'BUILD_NUMBER must be numeric'; exit 20 ;;
                    esac
                    test -f "${CLOUD_SSH_KEY}" || {
                        echo "Missing Cloud SSH key: ${CLOUD_SSH_KEY}"
                        exit 21
                    }

                    remote_dir="/tmp/linkrag-rag-prod-jenkins-${BUILD_NUMBER}"
                    ssh_opts="-i ${CLOUD_SSH_KEY} -o BatchMode=yes -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

                    ssh ${ssh_opts} "${CLOUD_USER}@${CLOUD_HOST}" \
                        "mkdir -p '${remote_dir}'"
                    scp ${ssh_opts} \
                        linkrag-rag-source.tar.gz \
                        deploy/scripts/build-production-on-cloud.sh \
                        "${CLOUD_USER}@${CLOUD_HOST}:${remote_dir}/"
                    ssh ${ssh_opts} "${CLOUD_USER}@${CLOUD_HOST}" \
                        "bash '${remote_dir}/build-production-on-cloud.sh' '${BUILD_NUMBER}' '${COMMIT_SHORT}' '${remote_dir}/linkrag-rag-source.tar.gz'"
                '''
            }
        }
    }

    post {
        always {
            sh '''
                case "${BUILD_NUMBER}" in
                    ''|*[!0-9]*) exit 0 ;;
                esac
                if [ -f "${CLOUD_SSH_KEY}" ]; then
                    ssh -i "${CLOUD_SSH_KEY}" \
                        -o BatchMode=yes \
                        -o IdentitiesOnly=yes \
                        -o StrictHostKeyChecking=accept-new \
                        "${CLOUD_USER}@${CLOUD_HOST}" \
                        "rm -rf '/tmp/linkrag-rag-prod-jenkins-${BUILD_NUMBER}'" || true
                fi
                rm -f linkrag-rag-source.tar.gz
            '''
        }
        success { echo "Production deployed from commit ${env.COMMIT_SHORT}" }
        failure { echo 'Production build or deployment failed.' }
    }
}
