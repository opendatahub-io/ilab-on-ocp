# ilab-on-ocp

This repo will serve as the central location for the Containerfiles and yamls needed to deploy [Instructlab](https://instructlab.ai/) onto an OpenShift cluster with RHOAI.

## Requirements
The following Operators must be installed on the cluster

* Red Hat - Authorino
* NVIDIA GPU Operator
* Node Feature Discovery
* Red Hat OpenShift AI
* Red Hat OpenShift Serverless
* Red Hat OpenShift Service Mesh

### NVIDIA GPU Operator
A ClusterPolicy must be deployed. The definition provided when clicking the "Create ClusterPolicy" although generic installs all required components.

### Accelerator Profile
An accelerator profile must be defined within the RHOAI dashboard or via CLI to enable GPU acceleration.

```
apiVersion: v1
items:
- apiVersion: dashboard.opendatahub.io/v1
  kind: AcceleratorProfile
  metadata:
    name: gpu
    namespace: redhat-ods-applications
  spec:
    displayName: gpu
    enabled: true
    identifier: nvidia.com/gpu
    tolerations: []
```

### Signed Certificate
A signed certificate ensures that there not unnecessary issues when performing the training pipeline.

To deploy a signed certificate in cluster follow [trusted cluster cert](signed-certificate/README.md)

### Object Storage
This solution requires object storage to be in place either through S3 or using Noobaa.

If you are using Noobaa apply the following [tuning paramters](noobaa/README.md)

## Standalone Deployment

See [standalone](standalone/README.md) for instructions on deploying the Instructlab solution
without the need for RHOAI.
To generate the `standalone.py` script, run the following command ([ruff](https://docs.astral.sh/ruff/installation/) tool must be installed):

```bash
make standalone
```

## Developer setup

To collaborate on this repository, please follow these steps:

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/)
2. Run following commands to prepare your local environment
    ```bash
    uv sync
    source .venv/bin/activate
    ```
