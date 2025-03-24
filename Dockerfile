FROM registry.access.redhat.com/ubi8/python-312:1

ARG SOURCE_CODE=.

# Default for ubi8/python
WORKDIR /opt/app-root/src/pipelines/distributed-ilab

COPY ${SOURCE_CODE} .

USER root

RUN echo "Installing Runtime Dependencies" && \
    dnf install -y skopeo && dnf clean all && \
    pip install --no-cache-dir -r requirements.txt && \
    chgrp -R 0 . && \
    chmod -R g=u . && \
    mv mixtral-tokenizer /models

USER default

# Default for ubi8/python
WORKDIR /opt/app-root/src

LABEL name="odh-ml-pipelines-runtime-generic" \
    summary="Generic runtime image for pipeline tasks with embedded managed pipelines." \
    description="Generic runtime image for pipeline tasks with embedded managed pipelines." \
    summary="odh-ml-pipelines-runtime-generic" \
    maintainer="['managed-open-data-hub@redhat.com']" \
    io.openshift.expose-services="" \
    io.k8s.display-name="odh-ml-pipelines-runtime-generic" \
    io.k8s.description="odh-ml-pipelines-runtime-generic"
