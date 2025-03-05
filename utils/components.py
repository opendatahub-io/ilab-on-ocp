# type: ignore

from kfp import dsl

from .consts import RHELAI_IMAGE, RUNTIME_GENERIC_IMAGE, TOOLBOX_IMAGE


@dsl.container_component
def pvc_to_mt_bench_op(mt_bench_output: dsl.Output[dsl.Artifact], pvc_path: str):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {mt_bench_output.path}"],
    )


@dsl.container_component
def pvc_to_mt_bench_branch_op(
    mt_bench_branch_output: dsl.Output[dsl.Artifact], pvc_path: str
):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {mt_bench_branch_output.path}"],
    )


@dsl.container_component
def pvc_to_mmlu_branch_op(mmlu_branch_output: dsl.Output[dsl.Artifact], pvc_path: str):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {mmlu_branch_output.path}"],
    )


@dsl.component(base_image=RUNTIME_GENERIC_IMAGE, install_kfp_package=False)
def upload_model_op(
    model: dsl.Output[dsl.Model],
    output_oci_model_uri: str = None,
    output_oci_registry_secret: str = None,
    output_modelcar_base_image: str = None,
    run_id: str = None,
    run_name: str = None,
    output_model_name: str = None,
    output_model_version: str = None,
    output_model_registry_api_url: str = None,
    output_model_registry_name: str = None,
    pvc_path: str = "/output/model",
    oci_temp_dir: str = "/output",
):
    import base64
    import os
    import pathlib
    import shutil
    import subprocess
    import tempfile
    import time
    import urllib.parse

    from model_registry import ModelRegistry

    model.name = "model"

    with open(
        "/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r"
    ) as ns_file:
        pod_namespace = ns_file.readline()

    if output_oci_model_uri:
        import kubernetes.client
        import kubernetes.config
        from olot.basics import oci_layers_on_top

        kubernetes.config.load_incluster_config()
        secret = kubernetes.client.CoreV1Api().read_namespaced_secret(
            output_oci_registry_secret,
            pod_namespace,
        )

        if ".dockerconfigjson" in secret.data:
            push_config_raw = base64.b64decode(secret.data[".dockerconfigjson"])
        else:
            push_config_raw = base64.b64decode(secret.data[".dockercfg"])

        if output_oci_model_uri.startswith("oci://"):
            output_oci_model_uri = output_oci_model_uri[len("oci://") :]

        model.uri = "oci://" + output_oci_model_uri

        # Strip the oci:// or docker:// prefix if provided
        if output_modelcar_base_image.startswith("oci://"):
            output_modelcar_base_image = output_modelcar_base_image[len("oci://") :]
        elif output_modelcar_base_image.startswith("docker://"):
            output_modelcar_base_image = output_modelcar_base_image[len("docker://") :]

        with tempfile.TemporaryDirectory("-modelcar", dir=oci_temp_dir) as t:
            print(
                f"\n---- Downloading the Modelcar base image {output_modelcar_base_image} ----"
            )

            tries = 0

            while True:
                try:
                    tries += 1
                    subprocess.run(
                        [
                            "skopeo",
                            "copy",
                            "--multi-arch",
                            "all",
                            "--remove-signatures",
                            "docker://" + output_modelcar_base_image,
                            "oci:" + t + ":latest",
                        ],
                        check=True,
                    )
                    break
                except Exception as e:
                    if tries >= 3:
                        raise

                    print(
                        f"Failed to pull the Modelcar base image on attempt {tries}/3: {e}"
                    )

            model_files = []

            for root, _, files in os.walk(pvc_path):
                for file in files:
                    file_path = os.path.join(root, file)
                    model_files.append(file_path)

            print(
                "\n---- Adding the model files to the /models directory on the base image ----"
            )
            oci_layers_on_top(pathlib.Path(t), model_files)

            print("\n---- Pushing the Modelcar to " + output_oci_model_uri + " ----")
            with tempfile.NamedTemporaryFile() as push_config:
                push_config.write(push_config_raw)
                push_config.flush()
                tries = 0

                while True:
                    try:
                        tries += 1
                        subprocess.run(
                            [
                                "skopeo",
                                "copy",
                                "--dest-authfile",
                                push_config.name,
                                "--multi-arch",
                                "all",
                                "oci:" + t + ":latest",
                                "docker://" + output_oci_model_uri,
                            ],
                            check=True,
                        )
                        break
                    except Exception as e:
                        if tries >= 3:
                            raise

                        print(
                            f"Failed to push the Modelcar image on attempt {tries}/3: {e}"
                        )
                        time.sleep(1)

    else:
        print(
            f"\n---- Copying the model to the model path {model.path} to be uploaded to S3 ----"
        )
        shutil.copytree(pvc_path, model.path)

    if not output_model_registry_api_url:
        return

    print(
        f"\n---- Registering the Modelcar as {output_model_name} with the version {output_model_version} ----"
    )

    with open("/var/run/secrets/kubernetes.io/serviceaccount/token", "r") as token_file:
        token = token_file.read()

    # Extract the port out of the URL because the ModelRegistry client expects those as separate arguments.
    model_registry_api_url_parsed = urllib.parse.urlparse(output_model_registry_api_url)
    model_registry_api_url_port = model_registry_api_url_parsed.port

    if model_registry_api_url_port:
        model_registry_api_server_address = output_model_registry_api_url.replace(
            model_registry_api_url_parsed.netloc,
            model_registry_api_url_parsed.hostname,
        )
    else:
        if model_registry_api_url_parsed.scheme == "http":
            model_registry_api_url_port = 80
        else:
            model_registry_api_url_port = 443

        model_registry_api_server_address = output_model_registry_api_url

    if not model_registry_api_url_parsed.scheme:
        model_registry_api_server_address = (
            "https://" + model_registry_api_server_address
        )

    tries = 0

    while True:
        try:
            tries += 1
            registry = ModelRegistry(
                server_address=model_registry_api_server_address,
                port=model_registry_api_url_port,
                author="InstructLab Pipeline",
                user_token=token,
            )

            registered_model = registry.register_model(
                name=output_model_name,
                version=output_model_version,
                uri=model.uri,
                model_format_name="vLLM",
                model_format_version=None,
                metadata={
                    "_registeredFromPipelineRunId": run_id,
                    "_registeredFromPipelineRunName": run_name,
                    "_registeredFromPipelineProject": pod_namespace,
                },
            )
            break
        except Exception as e:
            if tries >= 3:
                raise

            print(f"Failed to register the model on attempt {tries}/3: {e}")
            time.sleep(1)

    # Get the model version ID to add as metadata on the output model artifact
    tries = 0

    while True:
        try:
            tries += 1
            model_version_id = registry.get_model_version(
                output_model_name, output_model_version
            ).id
            break
        except Exception as e:
            if tries >= 3:
                raise

            print(f"Failed to get the model ID on attempt {tries}/3: {e}")
            time.sleep(1)

    # If output_model_registry_name is not provided, parse it from the URL.
    if not output_model_registry_name:
        output_model_registry_name = urllib.parse.urlparse(
            output_model_registry_api_url
        ).hostname.split(".")[0]

        if output_model_registry_name.endswith("-rest"):
            output_model_registry_name = output_model_registry_name[: -len("-rest")]

    model.metadata["modelRegistryName"] = output_model_registry_name
    model.metadata["registeredModelName"] = output_model_name
    model.metadata["modelVersionName"] = output_model_version
    model.metadata["modelVersionId"] = model_version_id
    model.metadata["registeredModelId"] = registered_model.id


@dsl.component(base_image=RUNTIME_GENERIC_IMAGE, install_kfp_package=False)
def model_to_pvc_op(model: dsl.Input[dsl.Model], pvc_path: str = "/model"):
    import os
    import os.path
    import shutil

    # shutil.copytree fails with "Operation Not Permitted" but doing one file at a time works for some reason.
    for f in os.listdir(model.path):
        src = os.path.join(model.path, f)
        dest = os.path.join(pvc_path, f)
        print(f"Copying {src} to {dest}")
        if os.path.isdir(src):
            shutil.copytree(src, dest)
        else:
            shutil.copy(src, dest)


@dsl.container_component
def ilab_importer_op(repository: str, release: str, base_model: dsl.Output[dsl.Model]):
    return dsl.ContainerSpec(
        RHELAI_IMAGE,
        ["/bin/sh", "-c"],
        [
            f"ilab --config=DEFAULT model download --repository {repository} --release {release} --model-dir {base_model.path}"
        ],
    )
