import os

DEFAULT_PYTHON_IMAGE = "quay.io/modh/odh-generic-data-science-notebook:v3-20250117"
DEFAULT_TOOLBOX_IMAGE = "registry.redhat.io/ubi9/toolbox:9.5"
DEFAULT_OC_IMAGE = "registry.redhat.io/openshift4/ose-cli:v4.15.0"
DEFAULT_RHELAI_IMAGE = (
    "registry.redhat.io/rhelai1/instructlab-nvidia-rhel9:1.4.1-1739870750"
)
DEFAULT_RUNTIME_GENERIC_IMAGE = (
    "quay.io/opendatahub/ds-pipelines-runtime-generic:latest"
)

PYTHON_IMAGE = os.getenv("PYTHON_IMAGE", DEFAULT_PYTHON_IMAGE)
TOOLBOX_IMAGE = os.getenv("TOOLBOX_IMAGE", DEFAULT_TOOLBOX_IMAGE)
OC_IMAGE = os.getenv("OC_IMAGE", DEFAULT_OC_IMAGE)
RHELAI_IMAGE = os.getenv("RHELAI_IMAGE", DEFAULT_RHELAI_IMAGE)
RUNTIME_GENERIC_IMAGE = os.getenv(
    "RUNTIME_GENERIC_IMAGE", DEFAULT_RUNTIME_GENERIC_IMAGE
)
TEACHER_CONFIG_MAP = "teacher-server"
TEACHER_SECRET = "teacher-server"
JUDGE_CONFIG_MAP = "judge-server"
JUDGE_SECRET = "judge-server"
