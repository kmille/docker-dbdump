FROM python:3.14-alpine3.24 AS builder
RUN pip install poetry
COPY . /app
WORKDIR /app
RUN poetry build --format=wheel


FROM python:3.14-alpine3.24

LABEL org.opencontainers.image.source=https://github.com/kmille/docker-dbdump
LABEL org.opencontainers.image.description="docker-dbdump – python script to create docker database backups"
LABEL org.opencontainers.image.licenses=MIT

ENV PYTHONUNBUFFERED=TRUE
RUN apk add --no-cache bash docker gzip

COPY --from=builder /app/dist/docker_dbdump*.whl .
RUN pip install docker_dbdump*.whl && \
    rm docker_dbdump*.whl

CMD ["/usr/local/bin/docker-dbdump"]
