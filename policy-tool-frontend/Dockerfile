FROM nginx:alpine

# Create the dashboard directory
RUN mkdir -p /usr/share/nginx/html/dashboard

# We don't necessarily NEED to copy files here if we use volumes in compose,
# but it's good practice for a standalone image.
COPY . /usr/share/nginx/html/dashboard/

# Expose port 80 for Traefik
EXPOSE 80