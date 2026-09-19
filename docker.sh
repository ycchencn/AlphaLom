#!/bin/bash
# AlphaLom Docker 构建与部署脚本
# 用法: ./shell_build_docker.sh [command]

set -e

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 镜像名称
BASE_BE_IMAGE="alphalom-be-base"
BASE_FE_IMAGE="alphalom-fe-base"
SERVICE_IMAGE="alphalom-service"

# 打印带颜色的信息
info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示帮助信息
show_help() {
    cat << EOF
AlphaLom Docker 构建与部署工具

用法: $0 [command]

命令:
  base        构建基础镜像 (BE + FE)
  base-be     仅构建后端基础镜像
  base-fe     仅构建前端基础镜像
  build       构建服务镜像
  up          启动所有服务
  down        停止所有服务
  restart     重启所有服务
  logs        查看服务日志 (follow 模式)
  status      查看服务状态
  clean       清理未使用的镜像和容器
  all         完整构建 (base + build + up)
  help        显示此帮助信息

示例:
  $0 base       # 构建基础镜像
  $0 build      # 构建服务镜像
  $0 up         # 启动服务
  $0 all        # 一键完整构建并启动

EOF
}

# 构建后端基础镜像
build_base_be() {
    info "构建后端基础镜像: ${BASE_BE_IMAGE}"
    docker build -t ${BASE_BE_IMAGE} --file ./install/DockerfileBase .
    success "后端基础镜像构建完成"
}

# 构建前端基础镜像
build_base_fe() {
    info "构建前端基础镜像: ${BASE_FE_IMAGE}"
    docker build -t ${BASE_FE_IMAGE} --file ./install/DockerfileBaseFE .
    success "前端基础镜像构建完成"
}

# 构建所有基础镜像
build_base() {
    info "构建所有基础镜像..."
    build_base_be
    build_base_fe
    success "所有基础镜像构建完成"
}

# 构建服务镜像
build_service() {
    info "构建服务镜像: ${SERVICE_IMAGE}"
    # 可选: 清理缓存
    # rm -rf ./job/df_cache/*
    # rm -rf ./service/cache/*
    docker build -t ${SERVICE_IMAGE} --file ./Dockerfile .
    success "服务镜像构建完成"
}

# 启动服务
start_services() {
    info "启动所有服务..."
    docker compose up -d
    success "所有服务已启动"
}

# 停止服务
stop_services() {
    info "停止所有服务..."
    docker compose down
    success "所有服务已停止"
}

# 重启服务
restart_services() {
    info "重启所有服务..."
    docker compose restart
    success "所有服务已重启"
}

# 查看日志
show_logs() {
    info "查看服务日志 (Ctrl+C 退出)..."
    docker compose logs -f
}

# 查看状态
show_status() {
    info "服务状态:"
    docker compose ps
}

# 清理未使用的资源
clean_resources() {
    warn "即将清理未使用的镜像和容器..."
    read -p "确认继续? (y/N) " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "清理未使用的容器..."
        docker container prune -f
        info "清理未使用的镜像..."
        docker image prune -f
        info "清理未使用的网络..."
        docker network prune -f
        success "清理完成"
    else
        info "已取消清理"
    fi
}

# 完整构建
build_all() {
    info "开始完整构建流程..."
    build_base
    build_service
    start_services
    success "完整构建完成，服务已启动!"
}

# 主逻辑
case "${1:-}" in
    base)
        build_base
        ;;
    base-be)
        build_base_be
        ;;
    base-fe)
        build_base_fe
        ;;
    build)
        build_service
        ;;
    up)
        start_services
        ;;
    down)
        stop_services
        ;;
    restart)
        restart_services
        ;;
    logs)
        show_logs
        ;;
    status)
        show_status
        ;;
    clean)
        clean_resources
        ;;
    all)
        build_all
        ;;
    help|--help|-h)
        show_help
        ;;
    "")
        # 默认行为: 构建服务镜像并启动 (保持向后兼容)
        warn "未指定命令，执行默认操作: 构建服务镜像并启动"
        warn "提示: 使用 '$0 help' 查看所有可用命令"
        build_service
        start_services
        ;;
    *)
        error "未知命令: $1"
        echo
        show_help
        exit 1
        ;;
esac
