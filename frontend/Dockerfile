# ============================================
# StressForge Frontend — Multi-Arch Nginx Dockerfile
# ============================================
FROM nginx:1.27-alpine

LABEL maintainer="stressforge"
LABEL description="StressForge Dashboard Frontend"

# Remove default nginx content
RUN rm -rf /usr/share/nginx/html/*

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Copy static files
COPY index.html /usr/share/nginx/html/
COPY css/ /usr/share/nginx/html/css/
COPY js/ /usr/share/nginx/html/js/

# Expose port
EXPOSE 80

# Health check
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://localhost:80/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
