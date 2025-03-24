# Configure the Input Base Model (S3 or OCI)

The input model to be fine-tuned must either be in either an S3-Compliant object store or OCI repository. How the
InstructLab pipeline downloads the input model varies depending on the method used.

## OCI Input Model

To utilize the OCI input, ensure the following:
* The input model is located in an oci compliant repository (e.g: quay.io, registry.redhat.io, etc.)
* The input model follows the [model car format]
* The host OCP cluster is configured to allow pods to pull this model care image
  * One way to do this is to configure the [cluster global pull secrets] (if you are using a private registry)
* You have the full oci path to the model for example: `oci://registry.redhat.io/rhelai1/modelcar-granite-7b-starter:1.4`

## S3-Compliant Object store

For utilizing an S3-Compliant store for your input base model, you will need to upload this model to your bucket.

We will be working with the [granite-7b-starter].

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

[model car format]: https://kserve.github.io/website/latest/modelserving/storage/oci/#prepare-an-oci-image-with-model-data
[cluster global pull secrets]: https://docs.redhat.com/en/documentation/openshift_container_platform/latest/html/images/managing-images#images-update-global-pull-secret_using-image-pull-secrets
[granite-7b-starter]: https://catalog.redhat.com/software/containers/rhelai1/granite-7b-starter/667ebf10abaa082bcf96ea6a
