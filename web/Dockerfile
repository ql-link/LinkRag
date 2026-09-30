# LinkRag Web 运行镜像：只打包已构建好的 dist/，由 Nginx 提供静态文件。
# 构建前先在 web/ 下执行 npm ci && npm run build（Jenkins 在 node 容器中完成，并先跑 typecheck / test）。
# 默认 Nginx 配置把 /api/ 转发到同一 Docker 网络内的 tolink-rag:8000；各环境可挂载自己的配置覆盖
# /etc/nginx/conf.d/default.conf（Dev 见 deploy/dev-server/nginx.conf，生产保存在服务器上）。
FROM nginx:1.27-alpine

COPY deploy/nginx.default.conf /etc/nginx/conf.d/default.conf
COPY dist/ /usr/share/nginx/html/

EXPOSE 80
