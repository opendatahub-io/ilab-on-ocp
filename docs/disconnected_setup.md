# Disconnected Cluster Setup

Disconnected environments require additional configuration, see below for details.

##### Mirror Required Images:

In a disconnected environment, you must mirror the following container images to your internal registry before
running the pipeline. Use tools like `oc adm release mirror`, `skopeo`, or `oras` to mirror these images:

- `registry.redhat.io/ubi9/toolbox@sha256:<sha-hash>`
- `registry.redhat.io/openshift4/ose-cli@<sha-hash>`
- `registry.redhat.io/rhelai1/instructlab-nvidia-rhel9@sha256:<sha-hash>`
- `registry.redhat.io/rhelai1/skills-adapter-v3@sha256:<sha-hash>`
- `registry.redhat.io/rhelai1/knowledge-adapter-v3@sha256:<sha-hash>`
- `registry.redhat.io/rhelai1/mixtral-8x7b-instruct-v0-1@sha256:<sha-hash>`
- `registry.redhat.io/rhelai1/prometheus-8x7b-v2-0@sha256:<sha-hash>`
- `quay.io/modh/odh-generic-data-science-notebook@sha256:<sha-hash>`
- `quay.io/modh/vllm@sha256:<sha-hash>`
- `quay.io/opendatahub/workbench-images@sha256:<sha-hash>`
- `ghcr.io/oras-project/oras:main@sha256:<sha-hash>`

##### 500GB PersistentVolumeClaim (PVC) for Mixtral:

The proposed method to deploy Mixtral requires a **500GB PVC**.
- In a **disconnected cluster**, ensure that your OpenShift environment has sufficient storage capacity and a **StorageClass** configured to provision this PVC.
- If automatic PVC creation fails, you may need to manually create a PersistentVolume (PV) and bind it to a PVC.

##### Accessible git repository with the taxonomy:

The iLab pipeline uses a taxonomy git repository, which should be accessible from the disconnected cluster

##### Handling Self Signed TLS connections

Any external connections requiring custom CA trust should be configured using [RHOAI platform level CA bundles]

This applies to the following:

* Teacher and Judge models
* Taxonomy Repo, including any repositories referenced in `qna.yaml` files
* Any OCI registry whether it is used for Input model (to be finetuned) or the output model

[RHOAI platform level CA bundles]: https://docs.redhat.com/en/documentation/red_hat_openshift_ai_self-managed/2.18/html/installing_and_uninstalling_openshift_ai_self-managed_in_a_disconnected_environment/working-with-certificates_certs#adding-a-ca-bundle_certs
