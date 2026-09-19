# ===== 阶段一：构建 Vue 前端 =====
FROM alphalom-fe-base as frontend-builder
WORKDIR /build
COPY . .
RUN npx update-browserslist-db@latest
RUN npm run build

# ===== 阶段二：构建 Python 后端 =====
FROM alphalom-be-base
WORKDIR /app
COPY . .
# 从 frontend-builder 阶段复制前端构建产物
COPY --from=frontend-builder /build/dist ./dist
CMD ["python3", "run_app.py"]