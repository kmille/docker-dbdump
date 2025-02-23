FROM python:3.12-alpine3.21 AS builder
RUN pip install poetry
COPY . /app
WORKDIR /app
RUN poetry build --format=wheel


FROM python:3.12-alpine3.21
ENV PYTHONUNBUFFERED=TRUE
RUN apk add --no-cache bash docker gzip

COPY --from=builder /app/dist/docker_dbdump*.whl .
RUN pip install docker_dbdump*.whl && \
    rm docker_dbdump*.whl

CMD ["/usr/local/bin/docker-dbdump"]
