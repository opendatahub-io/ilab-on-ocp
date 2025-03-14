# Running InstructLab Pipeline with Data Science Pipelines on RHOAI

This file provides step-by-step instructions for setting up and using the Data Science Pipelines (DSP) for InstructLab iterations.

## Pre-requisites

* An OpenShift cluster with
  * Sufficient GPUs available for training.
    * At a minimum, a node with at least 4 GPUs such as an NVIDIA A100s
  * The following Operators already installed:
    * Red Hat - Authorino
    * Red Hat Openshift Serverless
    * Red Hat OpenShift Service Mesh v2
      * NOTE: v3 is not compatible with RHOAI
    * NVIDIA GPU Operator 24.6
      * NOTE: Because of a known issue with CUDA/Driver versions mismatch, you can only use this Operator version.
    * Red Hat Openshift AI and operator dependencies documented at [OpenShift AI Supported Configurations](https://access.redhat.com/articles/rhoai-supported-configs)
* Teacher and Judge models with a serving endpoint
    * If already setup you will need the endpoint, api key, and any CA bundles if needed for each model
    * If setting up your own using these instructions, you will need additional multi-node A100s or L40s for each model
* SDG taxonomy tree to utilize for Synthetic Data Generation (SDG)
  * see instructions for creating a [taxonomy tree]
  on how to set up your own taxonomy tree.
* An OpenShift AI installation, with the Training Operator and KServe components set to `Managed`
  * A data science project/namespace, in this document this will be referred to as `<data-science-project-name/namespace>`
* A [StorageClass] that supports dynamic provisioning with [ReadWriteMany] access mode (see step 3 below).
* An S3 object store such as AWS, or an alternative object storage solution that is S3-compliant such as Ceph, Nooba and MinIO.
* A locally installed `oc` command line tool to create and manage kubernetes resources.
* Ilab CLI (or Skopeo/Oras/etc.) for model downloads
* For Disconnected Clusters:
  * **Mirror Required Images**:

    In a disconnected environment, you must mirror the following container images to your internal registry before running the pipeline. Use tools like `oc adm release mirror`, `skopeo`, or `oras` to mirror these images:
    - `registry.redhat.io/ubi9/toolbox@sha256:<sha-hash>`
    - `registry.redhat.io/openshift4/ose-cli@<sha-hash>`
    - `registry.redhat.io/rhelai1/instructlab-nvidia-rhel9@sha256:<sha-hash>`
    - `registry.redhat.io/rhelai1/skills-adapter-v3@sha256:<sha-hash>`
    - `registry.redhat.io/rhelai1/knowledge-adapter-v3@sha256:<sha-hash>`
    - `registry.redhat.io/rhelai1/mixtral-8x7b-instruct-v0-1@sha256:<sha-hash>`
    - `registry.redhat.io/rhelai1/prometheus-8x7b-v2-0@sha256:<sha-hash>`
    - `quay.io/modh/odh-generic-data-science-notebook@sha256:<sha-hash>`
    - `quay.io/modh/vllm@sha256:<sha-hash>`
    - `quay.io/modh/vllm@sha256:<sha-hash>`
    - `quay.io/opendatahub/workbench-images@sha256:<sha-hash>`
    - `ghcr.io/oras-project/oras:main@sha256:<sha-hash>`

  * **500GB PersistentVolumeClaim (PVC) for Mixtral**:

    The proposed method to deploy Mixtral requires a **500GB PVC**.
    - In a **disconnected cluster**, ensure that your OpenShift environment has sufficient storage capacity and a **StorageClass** configured to provision this PVC.
    - If automatic PVC creation fails, you may need to manually create a PersistentVolume (PV) and bind it to a PVC.
  * **Accessible git repository with the taxonomy**:

    - The iLab pipeline uses a taxonomy git repository, which should be accessible from the disconnected cluster

[StorageClass]: https://kubernetes.io/docs/concepts/storage/storage-classes/
[taxonomy tree]: https://docs.redhat.com/en/documentation/red_hat_enterprise_linux_ai/1.2/html/creating_a_custom_llm_using_rhel_ai/customize_taxonomy_tree
[ReadWriteMany]: https://kubernetes.io/docs/concepts/storage/persistent-volumes/#access-modes

## Steps

Before running the training and evaluation steps we must complete the following steps:

1. [Prepare base model and push to object store](#prepare-base-model-and-push-to-object-store)
1. [Setting up Judge & Teacher model](#setting-up-judge--teacher-model)
    * [Deploy a judge model server](#deploy-a-judge-model-server-optional) (Optional)
    * [Deploy judge model serving details](#deploy-judge-model-serving-details)
    * [Deploy a teacher model server](#deploy-a-teacher-model-server-optional) (Optional)
    * [Deploy teacher model serving details](#deploy-teacher-model-serving-details)
1. [Setup NFS StorageClass](#optional---setup-nfs-storageclass) (Optional)
1. [Set up Accelerator Profile](#accelerator-profile)
1. [Set up TLS Certificates](#signed-certificate) (Optional)
1. [Set Up Data Science Pipelines Server and Run InstructLab Pipeline](#set-up-data-science-pipelines-server-and-run-instructLab-pipeline)

### Prepare base model and push to object store

You will need a base model to train the ilab pipeline on, so to begin, upload the [granite-7b-starter] model to your object store.

```bash
$ mkdir -p s3-data/
```

Download ilab model repository in s3-data model directory
```bash
# You can also use Oras or Skopeo cli tools to download the model
# If using other tools besides ilab, ensure that filenames are mapped
# appropriately
$ ilab model download --repository docker://registry.redhat.io/rhelai1/granite-7b-starter --release 1.2
$ cp -r <path-to-model-downloaded-dir>/rhelai1/granite-7b-starter s3-data/granite-7b-starter
```

Generate tar archive
```bash
$ cd s3-data
$ tar -czvf rhelai.tar.gz *
```

Upload the created tar archive to your object store.
```bash
# Default cache location for ilab model download is ~/.cache/instructlab/models
# The model should be copied in such a way that the *.safetensors are found in s3://your-bucket-name/teach-model/*.safetensors
s3cmd sync s3-data/granite-7b-starter s3://<your-bucket-name>/granite-7b-starter
```

[granite-7b-starter]: https://catalog.redhat.com/software/containers/rhelai1/granite-7b-starter/667ebf10abaa082bcf96ea6a

### Setting up Judge & Teacher model

The Teacher model is used for Synthetic Data Generation (SDG) while the Judge model is used for model evaluation.

For the Teacher model you need [mixtral-8x7b-instruct-v0-1] deployed with [skills-adapter-v3:1.2] and
[knowledge-adapter-v3:1.2] LoRA layered skills and knowledge adapters.

For the Judge model you will need the [prometheus-8x7b-v2-0 model].

If you already have these models deployed you can skip the deployment steps and go straight to the secret set up for
Judge and Teacher respectively.

[mixtral-8x7b-instruct-v0-1]: https://catalog.redhat.com/software/containers/rhelai1/mixtral-8x7b-instruct-v0-1/6682619da4ea27a10a36e4c6
[skills-adapter-v3:1.2]: https://catalog.redhat.com/software/containers/rhelai1/skills-adapter-v3/66a89d60ac8385376a3dabed
[knowledge-adapter-v3:1.2]: https://catalog.redhat.com/software/containers/rhelai1/knowledge-adapter-v3/66a89ce222c498e45a8e0042
[prometheus-8x7b-v2-0 model]: https://catalog.redhat.com/software/containers/rhelai1/prometheus-8x7b-v2-0/6682611224ba6617d472f451

#### Deploy a judge model server (optional)

To deploy a judge model server, perform the following steps:

1. Create a service account to be used for token authentication

    ```yaml
    apiVersion: v1
    kind: ServiceAccount
    metadata:
      name: judge-sa
      namespace: <data-science-project-name/namespace>
    ```

1.  Upload [prometheus-8x7b-v2-0 model] (Judge-Model) to the same object storage as before.

    For example using `ilab` to download and `s3cmd` to sync to object store you can do:
    ```bash
    # You can also use Oras or Skopeo cli tools to download the model
    # If using other tools besides ilab, ensure that filenames are mapped
    # appropriately
    ilab model download --repository docker://registry.redhat.io/rhelai1/prometheus-8x7b-v2-0 --release 1.2

    # Default cache location for ilab model download is ~/.cache/instructlab/models
    s3cmd sync path/to/model s3://your-bucket-name/judge-model/
    ```

1.  Navigate to the OpenShift AI dashboard
    * Choose **Data Science Projects** from the left hand menu and choose your data science project/namespace.
    * Select the **Connections** tab, and then click on the **Add connection** button. Enter the details of your S3 bucket (object store) and click **Add data connection**.

> [!NOTE]
> Note: Before following the next step - Ensure that the `CapabilityServiceMeshAuthorization` status is `True` in `DSCinitialization` resource.

4.  Create a model server instance
    * Navigate back to **Data Science Projects** page, select your namespace again, and then select the **Models** tab
    * On the right hand side select **Deploy model** under **Single-model serving platform**
    * Provide the **Model deployment name** of `mistral`
    * Under Serving runtime choose the serving runtime `vLLM Serving Runtime for Kserve`.
    * Leave **Model framework** and **Number of model server replicas to deploy** settings as default
    * Choose `Medium` for **Model server size**
    * Select `NVIDIA GPU` for **Accelerator**, and set **Number of accelerators** to 1
    * Check the `Make deployed models available through an external route` box.
    * Under token authentication check the `Require token authentication` box, write the name of the service account that we have created above (`judge-sa`)
    * Choose the existing data connection created earlier, and provide the path to the model (in this case, `judge-model`)
    * Leave all other parameters as default/as-is.
    * Click deploy.

[prometheus-8x7b-v2-0 model]: https://catalog.redhat.com/software/containers/rhelai1/prometheus-8x7b-v2-0/6682611224ba6617d472f451

#### Deploy judge model serving details

With the judge model deployed, create some configuration files to provide the model details to the ilab pipeline

1.  Create a ConfigMap containing the judge model serving details
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: judge-server
      namespace: <data-science-project-name/namespace>
    data:
      JUDGE_NAME: <judge-model-name>          # Name of the judge model or deployment
      JUDGE_ENDPOINT: <judge-model-endpoint>  # Model serving endpoint, Sample format - `https://<deployed-model-server-endpoint>/v1`
      ca.crt: |  # Optional, used to use TLS-encrypted connection with model server
        -----BEGIN CERTIFICATE-----
        <various PEM-formatted Certs>
        -----END CERTIFICATE-----
    ```

1.  Create a Secret containing the judge model api key

    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: judge-server
      namespace: <data-science-project-name/namespace>
    type: Opaque
    stringData:
      JUDGE_API_KEY: <judge-model-api-key>  # Deployed model-server auth token
    ```

    If you deployed the Judge server model using the optional instructions above then you can retrieve `JUDGE_API_KEY` by
    running the following command:

    ```bash
    JUDGE_API_KEY=$(oc -n <data-science-project-name/namespace> create token judge-sa)
    ```

#### Deploy a teacher model server (Optional)

Unlike the Judge model we have to deploy the Teacher model manually on RHOAI, this consists of deploying the K8s resources
using `oc`.

1. First, upload the Teacher model to s3 if it does not already exist there:

    ```bash
    # You can also use ORAS or Skopeo cli tools to download the model
    # If using other tools besides ilab, ensure that filenames are mapped
    # appropriately
    ilab model download --repository docker://registry.redhat.io/rhelai1/mixtral-8x7b-instruct-v0-1 --release 1.2

    # Default cache location for ilab model download is ~/.cache/instructlab/models
    # The model should be copied in such a way that the *.safetensors are found in s3://your-bucket-name/teach-model/*.safetensors
    s3cmd sync path/to/model s3://your-bucket-name/teach-model/
    ```

1.  Deploy the following `yaml` called `pre_requisites.yaml` to the `<data-science-project-name/namespace>`
    <details>

    <summary>pre_requisites.yaml</summary>

    ```yaml
    ---
    kind: ServiceAccount
    apiVersion: v1
    metadata:
      name: mixtral-sa
    ---
    kind: Role
    apiVersion: rbac.authorization.k8s.io/v1
    metadata:
      name: mixtral-view-role
      labels:
        opendatahub.io/dashboard: 'true'
    rules:
      - verbs:
          - get
        apiGroups:
          - serving.kserve.io
        resources:
          - inferenceservices
        resourceNames:
          - mixtral
    ---
    kind: RoleBinding
    apiVersion: rbac.authorization.k8s.io/v1
    metadata:
      name: mixtral-view
      labels:
        opendatahub.io/dashboard: 'true'
    subjects:
      - kind: ServiceAccount
        name: mixtral-sa
    roleRef:
      apiGroup: rbac.authorization.k8s.io
      kind: Role
      name: mixtral-view-role
    ---
    kind: PersistentVolumeClaim
    apiVersion: v1
    metadata:
      name: mixtral-serving-ilab
      labels:
        opendatahub.io/dashboard: 'true'
    spec:
      accessModes:
        - ReadWriteOnce
      resources:
        requests:
          storage: 200Gi
      storageClassName: standard-csi
      volumeMode: Filesystem
    ```

    </details>

    ```bash
    oc -n <data-science-project-name/namespace> apply -f pre_requisites.yaml
    ```

1.  Next, ensure object storage connection details are provided.


    To do this, you will need to ensure that the `storage-config` secret exists in the `<data-science-project-name/namespace>` namespace, and this `storage-config` has the configuration for the bucket where the teacher model is stored.

    <details>

    <summary>storage-config.yaml</summary>

    ```yaml
    apiVersion: v1
    stringData:
      aws-connection-my-bucket: |
        {
          "type": "s3",
          "access_key_id": "your_accesskey",
          "secret_access_key": "your_secretkey",
          "endpoint_url": "https://s3-us-east-2.amazonaws.com",
          "bucket": "mybucket",
          "default_bucket": "mybucket",
          "region": "us-east-2"
        }
    kind: Secret
    metadata:
      name: storage-config
    type: Opaque
    ```

    </details>

    If this secret does not exist in this namespace, then create it using `oc`:

    ```bash
    oc -n <data-science-project-name/namespace> apply -f storage-config.yaml
    ```

    If it does exist, then ensure there is an entry for the bucket that stores the teacher model.
    The `key` is used in the `InferenceService` spec below.

1.  Finally, we need to create the custom `ServingRuntime` and `InferenceService`.

    Similar to above, deploy the following `yaml` files to the namespace `<data-science-project-name/namespace>`

    You will need to update the `spec.model.storage.path` in the `InferenceService` to match the path where the
    model files are stored in your bucket. The `key` should match the value in your `storage-config` secret that
    has the bucket credentials.  In our example above we use `aws-connection-my-bucket`.

    <details>
    <summary>servingruntime.mixtral.yaml</summary>

    ```yaml
    ---
    apiVersion: serving.kserve.io/v1alpha1
    kind: ServingRuntime
    metadata:
      annotations:
        opendatahub.io/accelerator-name: migrated-gpu
        opendatahub.io/apiProtocol: REST
        opendatahub.io/recommended-accelerators: '["nvidia.com/gpu"]'
        opendatahub.io/template-display-name: Mixtral ServingRuntime
        opendatahub.io/template-name: vllm-runtime
        openshift.io/display-name: mixtral
      labels:
        opendatahub.io/dashboard: "true"
      name: mixtral
    spec:
      annotations:
        prometheus.io/path: /metrics
        prometheus.io/port: "8080"
      containers:
      - args:
        - --port=8080
        - --model=/mnt/models
        - --served-model-name={{.Name}}
        - --distributed-executor-backend=mp
        command:
        - python
        - -m
        - vllm.entrypoints.openai.api_server
        env:
        - name: HF_HOME
          value: /tmp/hf_home
        image: quay.io/modh/vllm
        name: kserve-container
        ports:
        - containerPort: 8080
          protocol: TCP
        volumeMounts:
        - mountPath: /dev/shm
          name: shm
        - mountPath: /mnt
          name: mixtral-serve
      multiModel: false
      storageHelper:
        disabled: true
      supportedModelFormats:
      - autoSelect: true
        name: vLLM
      volumes:
      - name: mixtral-serve
        persistentVolumeClaim:
          claimName: mixtral-serving-ilab
      - emptyDir:
          medium: Memory
          sizeLimit: 2Gi
        name: shm
    ```

    </details>

    <details>

    <summary>inferenceservice.mixtral.yaml</summary>

    ```yaml
    ---
    apiVersion: serving.kserve.io/v1beta1
    kind: InferenceService
    metadata:
      annotations:
        openshift.io/display-name: mixtral
        security.opendatahub.io/enable-auth: "true"
        serving.knative.openshift.io/enablePassthrough: "true"
        sidecar.istio.io/inject: "true"
        sidecar.istio.io/rewriteAppHTTPProbers: "true"
      finalizers:
      - inferenceservice.finalizers
      labels:
        opendatahub.io/dashboard: "true"
      name: mixtral
    spec:
      predictor:
        maxReplicas: 1
        minReplicas: 1
        model:
          args:
          - --dtype=bfloat16
          - --tensor-parallel-size=4
          - --enable-lora
          - --max-lora-rank=64
          - --lora-dtype=bfloat16
          - --fully-sharded-loras
          - --lora-modules
          - skill-classifier-v3-clm=/mnt/models/skills
          - text-classifier-knowledge-v3-clm=/mnt/models/knowledge
          modelFormat:
            name: vLLM
          name: ""
          resources:
            limits:
              cpu: "4"
              memory: 60Gi
              nvidia.com/gpu: "4"
            requests:
              cpu: "4"
              memory: 60Gi
              nvidia.com/gpu: "4"
          runtime: mixtral
          storage:
            # the secret name of the secret deployed earlier
            key: aws-connection-my-bucket
            # update this to match the path in your bucket
            path: <prefix-path-to-mixtral-model-in-s3>
        tolerations:
        - effect: NoSchedule
          key: nvidia.com/gpu
          operator: Exists
    ```

    </details>


    Make sure to update the s3 path to the model in the InferenceService, then deploy these
    YAML files using the following commands:

    ```bash
    oc -n <data-science-project-name/namespace> apply -f servingruntime.mixtral.yaml
    oc -n <data-science-project-name/namespace> apply -f inferenceservice.mixtral.yaml
    ```

1.  Once completed, a new pod named `mixtral-predictor-0000#-deployment-<hash>` should be created.   If the pod does not come up successfully, you inspect the `.status` field for the `InferenceService` for issues.

    ```bash
    oc -n <data-science-project-name/namespace> get inferenceservice mixtral -o yaml
    ```

#### Deploy teacher model serving details

Similar to the judge model setup, create some configuration files to provide the model details to the ilab pipeline

1.  Create a ConfigMap containing the teacher model serving details
    ```yaml
    apiVersion: v1
    kind: ConfigMap
    metadata:
      name: teacher-server
      namespace: <data-science-project-name/namespace>
    data:
      model: <teacher-model-name>       # Name of the teacher model or deployment
      endpoint: <judge-model-endpoint>  # Model serving endpoint, Sample format - `https://<deployed-model-server-endpoint>/v1`
      ca.crt: |  # Optional, used to use TLS-encrypted connection with model server
        -----BEGIN CERTIFICATE-----
        <various PEM-formatted Certs>
        -----END CERTIFICATE-----
    ```

1.  Create a Secret containing the teacher model api key:

    ```yaml
    apiVersion: v1
    kind: Secret
    metadata:
      name: teacher-server
      namespace: <data-science-project-name/namespace>
    type: Opaque
    stringData:
      api_key:  <teacher-model-api-key>  # Deployed model-server auth token
    ```

> [!NOTE]
> Note: If using a custom CA certificate you must provide the relevant data in a ConfigMap. The config map name and
> key are then provided as a parameter to the pipeline as well as in the `teacher-model-details-k8s-secret` secret above.

    If you deployed the Teacher server model using the optional instructions above then you can retrieve `api_key` by
    running the following command:

    ```bash
    SDG_API_KEY=$(oc -n <data-science-project-name/namespace> create token mixtral-sa)
    ```

### (Optional) - Setup NFS StorageClass

> [!CAUTION]
> The image provided here is for test purposes only.
> Users must provide a production ready storageclass with ReadWriteMany capability.

This step is needed when the cluster doesn't have a storage provisioner capable of provisioning PersistentVolumeClaim with ReadWriteMany capability.

Installing the NFS CSI driver
```bash
$ curl -skSL https://raw.githubusercontent.com/kubernetes-csi/csi-driver-nfs/v4.9.0/deploy/install-driver.sh | bash -s v4.9.0 --
```

For deploying an in-cluster NFS server, apply [nfs-server-deployment.yaml] file

```bash
oc new-project nfs
oc apply -f ./sample-manifests/nfs-server-deployment.yaml
```

> [!NOTE]
> Note:  Check the root PersistentVolumeclaim that'll be created and the requested storage.

For creating NFS storage-class, apply [nfs-storage-class.yaml] file
```bash
oc apply -f ./sample-manifests/nfs-storage-class.yaml
```
[nfs-storage-class.yaml]:/sample-manifests/nfs-storage-class.yaml
[nfs-server-deployment.yaml]:/sample-manifests/nfs-server-deployment.yaml

### Accelerator Profile:
An accelerator profile must also be defined within the RHOAI dashboard or via CLI to enable GPU acceleration for model serving with Kserve Serving.

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
### Signed Certificate:
A signed certificate ensures that there are not any unnecessary issues when running the training pipeline.

To deploy a signed certificate in your cluster follow [trusted cluster cert](signed-certificate/README.md) documentation.

This will create the required resources in the cluster, including the required StorageClass.

### Set Up Data Science Pipelines Server and Run InstructLab Pipeline

Now we can continue to set up the required resources in our cluster.

The following resources will be created:

1. Secret
1. ClusterRole
1. ClusterRoleBinding
1. Pod

Create a secret resource that contains the credentials for your Object Storage (AWS S3 Bucket)

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: sdg-object-store-credentials
type: Opaque
stringData:
  bucket: <s3-bucket-name>             # The object store bucket containing SDG+Model+Taxonomy data. (Name of S3 bucket)
  access_key: <s3-access-key>          # The object store access key (AWS Access key ID)
  secret_key: <s3-secret-key>          # The object store secret key (AWS Secret Access Key)
  data_key: <s3-path-to-teacher-model-files>                  # The name of the tarball that contains SDG data.
  endpoint: <s3-endpoint>              # The object store endpoint
  region: <s3-region>                  # The region for the object store.
  verify_tls: true                     # Verify TLS for the object store.
```

Apply the yaml file to the cluster

Create a ServiceAccount, ClusterRole and ClusterRoleBinding

Provide access to the service account running the pipeline for accessing and manipulating related resources.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  namespace: <data-science-project-name/namespace>
  name: secret-access-role
rules:
  - apiGroups: [""]
    resources: ["pods", "pods/log", "configmaps", "persistentvolumeclaims", "secrets","events"]
    verbs: ["get", "list", "watch", "create", "update", "delete"]

  - apiGroups: ["batch"]
    resources: ["jobs"]
    verbs: ["get", "list", "create", "watch"]

  - apiGroups: ["kubeflow.org"]
    resources: ["pytorchjobs"]
    verbs: ["get", "list", "create", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: secret-access-binding
subjects:
  - kind: ServiceAccount
    name: <workbench-service-account-name> # created above in Step-2
    namespace: <data-science-project-name/namespace>
roleRef:
  kind: ClusterRole
  name: secret-access-role
  apiGroup: rbac.authorization.k8s.io
```
Apply the yaml to the cluster.

These are the required [RBAC configuration] which we are applying on the ServiceAccount.

#### Configure Data Science Pipeline Server:

From within the RHOAI dashboard, navigate to the **Data Science Pipelines** page and click **Configure pipeline server**. This will present you with a form where you can upload the credentials for the S3 bucket you created in the previous step.

<p align="center"><img src="assets/images/configure_pipeline_server.png" width=50%></p>

### Run the Pipeline

Now that all the cluster requirements have been setup, we are ready to upload and run our InstructLab pipeline!

#### Upload the Pipeline:

Now we can go back to our RHOAI Data Science Pipelines dashboard and select **Import pipeline**. We recommend importing the pipeline yaml directly from the github repo using: `https://raw.githubusercontent.com/opendatahub-io/ilab-on-ocp/refs/heads/main/pipeline.yaml`
<p align="center"><img src="assets/images/import_pipeline.png" width=50%\></p>

**Note**: While using a **Disconnected Cluster**, the pipeline should be imported from a file instead of a URL.Using a URL fails in disconnected clusters as they cannot connect to GitHub.

#### Create a Run:
Once the pipeline is uploaded we will be able to select **Create run** from the **Actions** dropdown. This will present us with a number of parameters we can set to customize our run. Click **Create run** at the bottom of the page to kick off your InstructLab pipeline.

<p align="center"><img src="assets/images/parameters.png" width=50%\></p>

#### Available Pipeline Parameters:

| Parameter | Definition |
|---------- | ---------- |
|`sdg_repo_url` | SDG parameter. Points to a taxonomy git repository|
|`sdg_repo_branch` | SDG parameter. Points to a branch within the taxonomy git repository. If set, has priority over sdg_repo_pr|
|`sdg_repo_pr` |SDG parameter. Points to a pull request against the taxonomy git repository|
|`sdg_base_model` |SDG parameter. LLM model used to generate the synthetic dataset|
|`sdg_scale_factor` |SDG parameter. The total number of instructions to be generated|
|`sdg_pipeline` |SDG parameter. Data generation pipeline to use. Available: 'simple', 'full', or a valid path to a directory of pipeline workflow YAML files. Note that 'full' requires a larger teacher model, Mixtral-8x7b.|
|`sdg_max_batch_len` |SDG parameter. Maximum tokens per gpu for each batch that will be handled in a single step.|
|`sdg_sample_size` | SDG parameter. Sampling size used for Synthetic Data Generation |
|`train_nproc_per_node` |Training parameter. Number of GPUs per each node/worker to use for training.|
|`train_nnodes` |Training parameter. Number of nodes/workers to train on.|
|`train_num_epochs_phase_1` |Training parameter for in Phase 1. Number of epochs to run training.|
|`train_num_epochs_phase_2` |Training parameter for in Phase 2. Number of epochs to run training.|
|`train_effective_batch_size_phase_1` |Training parameter for in Phase 1. The number of samples in a batch that the model should see before its parameters are updated.|
|`train_effective_batch_size_phase_2` |Training parameter for in Phase 2. The number of samples in a batch that the model should see before its parameters are updated.|
|`train_learning_rate_phase_1` |Training parameter for in Phase 1. How fast we optimize the weights during gradient descent. Higher values may lead to unstable learning performance. It's generally recommended to have a low learning rate with a high effective batch size.|
|`train_learning_rate_phase_2` |Training parameter for in Phase 2. How fast we optimize the weights during gradient descent. Higher values may lead to unstable learning performance. It's generally recommended to have a low learning rate with a high effective batch size.|
|`train_num_warmup_steps_phase_1` |Training parameter for in Phase 1. The number of steps a model should go through before reaching the full learning rate. We start at 0 and linearly climb up to train_learning_rate.|
|`train_num_warmup_steps_phase_2` |Training parameter for in Phase 2. The number of steps a model should go through before reaching the full learning rate. We start at 0 and linearly climb up to train_learning_rate.|
|`train_save_samples` |Training parameter. Number of samples the model should see before saving a checkpoint.|
|`train_max_batch_len` |Training parameter. Maximum tokens per gpu for each batch that will be handled in a single step.|
|`train_seed` |Training parameter. Random seed for initializing training.|
|`mt_bench_max_workers` |MT Bench parameter. Number of workers to use for evaluation with mt_bench or mt_bench_branch. Must be a positive integer or 'auto'.|
|`mt_bench_merge_system_user_message` |MT Bench parameter. Boolean indicating whether to merge system and user messages (required for Mistral based judges)|
|`final_eval_max_workers` |Final model evaluation parameter for MT Bench Branch. Number of workers to use for evaluation with mt_bench or mt_bench_branch. Must be a positive integer or 'auto'.|
|`final_eval_few_shots` |Final model evaluation parameter for MMLU. Number of question-answer pairs provided in the context preceding the question used for evaluation.|
|`final_eval_batch_size` |Final model evaluation parameter for MMLU. Batch size for evaluation. Valid values are a positive integer or 'auto' to select the largest batch size that will fit in memory.|
|`final_eval_merge_system_user_message` |Final model evaluation parameter for MT Bench Branch. Boolean indicating whether to merge system and user messages (required for Mistral based judges)|
|`k8s_storage_class_name` |A Kubernetes StorageClass name for persistent volumes. Selected StorageClass must support RWX PersistentVolumes.|

##### Suggested Parameters: Full Pipeline
To run the ilab Pipeline at full capabilities, we suggest using these values:
| Parameter | Suggested Value |
|---------- | ---------- |
|`sdg_repo_url` | https://github.com/instructlab/taxonomy.git |
|`sdg_repo_branch` | "" |
|`sdg_repo_pr` | 0 |
|`sdg_base_model` | s3://<BUCKET>/<PATH_TO_MODEL> |
|`sdg_scale_factor` | 30 |
|`sdg_pipeline` | "full" |
|`sdg_max_batch_len` | 5000 |
|`sdg_sample_size` | 1.0 |
|`train_nproc_per_node` | 2 |
|`train_nnodes` | 2 |
|`train_num_epochs_phase_1` | 7 |
|`train_num_epochs_phase_2` | 10 |
|`train_effective_batch_size_phase_1` | 128 |
|`train_effective_batch_size_phase_2` | 3840 |
|`train_learning_rate_phase_1` | 2e-05 |
|`train_learning_rate_phase_2` | 6e-06 |
|`train_num_warmup_steps_phase_1` | 1000 |
|`train_num_warmup_steps_phase_2` | 1000 |
|`train_save_samples` | 250000 |
|`train_max_batch_len` | 5000 |
|`train_seed` | 42 |
|`mt_bench_max_workers` | "auto" |
|`mt_bench_merge_system_user_message` | False |
|`final_eval_max_workers` | "auto" |
|`final_eval_few_shots` | 5 |
|`final_eval_batch_size` | "auto" |
|`final_eval_merge_system_user_message` | False |
|`k8s_storage_class_name` | standard |
Note that this will take a very long time, on the scale of double-digit hours of runtime.
##### Suggested Parameters: Development
Running the ilab pipeline at full capabilities takes a very long time, and with a good amount of resource consumption.
To create a e2e run that completes much quicker (at the expense of output quality), and with fewer resources (namely, GPU nodes) we suggest using these values instead:
| Parameter | Suggested Value |
|---------- | ---------- |
|`sdg_repo_url` | https://github.com/instructlab/taxonomy.git |
|`sdg_repo_branch` | "" |
|`sdg_repo_pr` | 0 |
|`sdg_base_model` | s3://<BUCKET>/<PATH_TO_MODEL> |
|`sdg_scale_factor` | 30 |
|`sdg_pipeline` | "simple" |
|`sdg_max_batch_len` | 5000 |
|`sdg_sample_size` | **0.0002** |
|`train_nproc_per_node` | **1** |
|`train_nnodes` | **1** |
|`train_num_epochs_phase_1` | **2** |
|`train_num_epochs_phase_2` | **2** |
|`train_effective_batch_size_phase_1` | **3840** |
|`train_effective_batch_size_phase_2` | 3840 |
|`train_learning_rate_phase_1` | **.0001** |
|`train_learning_rate_phase_2` | **.0001** |
|`train_num_warmup_steps_phase_1` | **800** |
|`train_num_warmup_steps_phase_2` | **800** |
|`train_save_samples` | **0** |
|`train_max_batch_len` | **20000** |
|`train_seed` | 42 |
|`mt_bench_max_workers` | "auto" |
|`mt_bench_merge_system_user_message` | False |
|`final_eval_max_workers` | "auto" |
|`final_eval_few_shots` | 5 |
|`final_eval_batch_size` | "auto" |
|`final_eval_merge_system_user_message` | False |
|`k8s_storage_class_name` | standard |

Using these parameters will allow a user to run the complete pipeline much quicker; in testing we have found this to take about 90 minutes.
Additionally, we can point the `judge-server` and `teacher-server` to the same Mistral model, which only uses 1 GPU, and the PyTorchJob configuration
specified here also only uses 2 training nodes of 1 GPU, so a total of 3 GPUs are required, rather than the 8-9 GPUs required for the full pipeline.
With that said, the output model quality is likely very poor, and these should only be used for testing purposes.
