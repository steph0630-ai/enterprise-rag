# CI/CD 流水线配置规范 (Jenkins/GitLab CI)

| 文档版本 | 修改日期 | 修改人 | 修改内容 |
|---------|---------|-------|---------|
| v1.0 | 2025-03-20 | 张明 | 初稿创建 |
| v1.1 | 2025-04-05 | 李华 | 增加安全检查阶段说明 |
| v1.2 | 2025-04-18 | 王强 | 细化缓存管理策略 |

**负责人**：张明 (z.ming@company.com)  
**生效日期**：2025-04-20  
**适用范围**：后端微服务、前端 Web 应用、数据管道类项目

---

## 1. 概述

本规范定义了公司内部基于 Jenkins 和 GitLab CI 的 CI/CD 流水线配置标准。所有新项目必须遵循此规范；存量项目需在下一个大版本迭代时完成迁移。规范旨在保证构建、测试、部署过程的一致性和可审计性。

## 2. 通用流水线阶段

所有流水线必须包含以下五个核心阶段（Stage），且顺序固定：

1. **build** – 编译/打包
2. **test** – 单元测试与静态检查
3. **security** – 安全扫描
4. **package** – 制品归档与镜像构建
5. **deploy** – 环境部署

### 2.1 阶段详细说明

| 阶段 | 必须执行的操作 | 失败处理 | 超时(分钟) |
|------|--------------|---------|-----------|
| build | `mvn clean compile` 或 `npm run build` | 立即终止 | 15 |
| test | `mvn test` + `sonar-scanner` 或 `npm test` + `eslint` | 记录失败，继续后续阶段 | 30 |
| security | `trivy image` / `snyk test` | 仅警告，不阻断 | 10 |
| package | `docker build` + `docker push` + 版本标签 | 立即终止 | 20 |
| deploy | `kubectl apply` 或 `helm upgrade` | 回滚至上一次稳定版本 | 15 |

> **注意**：test 阶段失败不会阻断后续阶段，但需要在 MR 评论中标注测试覆盖率未达标的模块。

## 3. Jenkins 流水线配置

### 3.1 Jenkinsfile 模板

所有 Java/Spring 项目使用以下模板结构：

```groovy
// Jenkinsfile
pipeline {
    agent {
        label 'linux-xlarge'
    }

    environment {
        DOCKER_REGISTRY = 'registry.company.com'
        IMAGE_NAME = "${DOCKER_REGISTRY}/${JOB_BASE_NAME}"
        IMAGE_TAG = "${env.BUILD_NUMBER}-${env.GIT_COMMIT.substring(0,7)}"
    }

    stages {
        stage('Build') {
            steps {
                sh 'mvn clean compile -DskipTests=true'
            }
        }

        stage('Test') {
            steps {
                sh 'mvn test'
                sh 'sonar-scanner -Dsonar.projectKey=${JOB_BASE_NAME} -Dsonar.host.url=http://sonarqube.company.com:9000'
            }
        }

        stage('Security Scan') {
            steps {
                sh 'trivy image --severity HIGH,CRITICAL --exit-code 1 ${IMAGE_NAME}:${IMAGE_TAG} || true'
            }
        }

        stage('Package & Push') {
            steps {
                sh 'docker build -t ${IMAGE_NAME}:${IMAGE_TAG} .'
                sh 'docker push ${IMAGE_NAME}:${IMAGE_TAG}'
            }
        }

        stage('Deploy to Staging') {
            when {
                branch 'develop'
            }
            steps {
                sh 'kubectl set image deployment/${JOB_BASE_NAME} ${JOB_BASE_NAME}=${IMAGE_NAME}:${IMAGE_TAG} -n staging'
            }
        }

        stage('Deploy to Production') {
            when {
                branch 'main'
            }
            steps {
                sh 'helm upgrade --install ${JOB_BASE_NAME} ./helm-chart --set image.tag=${IMAGE_TAG} -n production'
            }
        }
    }

    post {
        always {
            cleanWs()
        }
        failure {
            emailext(
                subject: "Pipeline Failed: ${env.JOB_NAME} (${env.BUILD_NUMBER})",
                to: "${env.CHANGE_AUTHOR_EMAIL}",
                body: "Pipeline execution failed. Please check: ${env.BUILD_URL}"
            )
        }
    }
}
```

### 3.2 关键参数说明

- **agent label**：`linux-xlarge` 对应 8C16G 构建节点，前端项目可使用 `frontend-builder`（4C8G）
- **IMAGE_TAG**：格式为 `${BUILD_NUMBER}-${短commit SHA}`，例如 `1284-abc1234`
- **Deploy 阶段**：仅当分支为 `develop` 或 `main` 时执行。`develop` 部署至 staging 命名空间，`main` 部署至 production

## 4. GitLab CI 配置

### 4.1 .gitlab-ci.yml 模板

适用于 Node.js / Go 项目：

```yaml
# .gitlab-ci.yml
stages:
  - build
  - test
  - security
  - package
  - deploy

variables:
  DOCKER_DRIVER: overlay2
  DOCKER_HOST: tcp://docker:2375

cache:
  key: ${CI_COMMIT_REF_SLUG}
  paths:
    - node_modules/
    - .npm/

build:
  stage: build
  image: node:18-alpine
  script:
    - npm ci --cache .npm --prefer-offline
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 1 week

test:
  stage: test
  image: node:18-alpine
  script:
    - npm test -- --coverage
    - npx eslint src/ --max-warnings 50
  artifacts:
    reports:
      coverage_report:
        coverage_format: cobertura
        path: coverage/cobertura-coverage.xml

security:
  stage: security
  image: aquasec/trivy:latest
  script:
    - trivy fs --severity HIGH,CRITICAL --exit-code 0 .
  allow_failure: true

package:
  stage: package
  image: docker:20.10.16
  services:
    - docker:20.10.16-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
  only:
    - develop
    - main

deploy-staging:
  stage: deploy
  image: bitnami/kubectl:latest
  script:
    - kubectl set image deployment/$CI_PROJECT_NAME $CI_PROJECT_NAME=$CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA -n staging
  only:
    - develop
  needs:
    - package

deploy-production:
  stage: deploy
  image: alpin/helm:3.12
  script:
    - helm upgrade --install $CI_PROJECT_NAME ./helm-chart --set image.tag=$CI_COMMIT_SHORT_SHA -n production
  only:
    - main
  needs:
    - package
```

### 4.2 缓存策略

- **npm 缓存**：将 `node_modules/` 和 `.npm/` 目录缓存，key 基于分支名称，避免跨分支污染
- **Maven 缓存**（Java 项目）：使用 `.m2/repository/` 路径，key 基于 `pom.xml` 的 checksum
- **Go 模块缓存**：缓存 `$GOPATH/pkg/mod/`，key 基于 `go.sum`

**过期策略**：缓存保留 7 天，超过 7 天未使用自动清理。

## 5. 环境变量管理

### 5.1 敏感信息

- **API Token、数据库密码**：必须使用 Jenkins Credentials 或 GitLab CI Variables (Masked)
- **非敏感变量**：如服务端口、日志级别，可使用项目根目录的 `.env` 文件，但需加入 `.gitignore`

### 5.2 必须定义的变量

| 变量名 | 用途 | 示例值 |
|-------|------|-------|
| `CI_PROJECT_NAME` | 项目名，用于 k8s deployment 名称 | `payment-service` |
| `CI_REGISTRY_IMAGE` | 镜像仓库地址 | `registry.company.com/payment-service` |
| `KUBECONFIG` | k8s 集群认证文件路径 | `/etc/deploy/kubeconfig-staging` |

## 6. 安全与合规要求

1. **镜像安全**：所有 push 到 registry 的镜像必须经过 `trivy` 扫描，CRITICAL 漏洞数量超过 3 个时，deploy 阶段自动跳过
2. **部署审批**：生产环境部署需要手动确认（Jen