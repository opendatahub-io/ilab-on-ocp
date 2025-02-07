# type: ignore

from typing import Optional

from kfp import dsl
from kfp.kubernetes import use_config_map_as_volume

from .consts import (
    JUDGE_CONFIG_MAP,
    RHELAI_IMAGE,
    RUNTIME_GENERIC_IMAGE,
    TEACHER_CONFIG_MAP,
    TOOLBOX_IMAGE,
)


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


@dsl.component(base_image=RUNTIME_GENERIC_IMAGE)
def test_model_connection(secret_name: str):
    import base64
    import json
    import os
    import sys
    import time

    import requests
    from kubernetes import client, config
    from kubernetes.client.rest import ApiException

    config.load_incluster_config()

    model_endpoint = ""
    model_name = ""
    model_api_key = ""
    with open(
        "/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r"
    ) as namespace_path:
        namespace = namespace_path.readline()

    with client.ApiClient() as api_client:
        core_api = client.CoreV1Api(api_client)

        try:
            secret = core_api.read_namespaced_secret(secret_name, namespace)
            print(f"Reading secret {secret_name} data...")
            model_api_key = base64.b64decode(secret.data["api_key"]).decode("utf-8")
            model_name = base64.b64decode(secret.data["model_name"]).decode("utf-8")
            model_endpoint = base64.b64decode(secret.data["endpoint"]).decode("utf-8")
        except (ApiException, KeyError) as e:
            print(f"""
            ############################################ ERROR #####################################################
            # Error reading {secret_name}. Ensure you created a secret with this name in namespace {namespace} and #
            # has 'api_key', 'model_name', and 'endpoint' present                                                  #
            ########################################################################################################
            """)
            sys.exit(1)

    request_auth = {"Authorization": f"Bearer {model_api_key}"}
    request_body = {
        "model": model_name,
        "messages": [{"role": "user", "content": "tell me a funny joke."}],
    }
    # Make 3 attempts
    for i in range(1, 3):
        resp = requests.post(
            f"{model_endpoint}/chat/completions",
            headers=request_auth,
            data=json.dumps(request_body),
            verify=os.environ["SDG_CA_CERT_PATH"],
        )
        if resp.status_code != 200:
            print(f"Model Server {model_name} is not available. Attempt {i}/3...")
            time.sleep(5)
        else:
            print(f"""
            ################### INFO #######################
            # Model Server {model_name} is up and running. #
            ################################################
            """)
            return
    print(f"""
    ############################################ ERROR ####################################################
    # Model Server {model_name} is unavailable. Ensure the model is up and it is ready to serve requests. #
    #######################################################################################################
    """)
    sys.exit(1)


@dsl.component(base_image=RUNTIME_GENERIC_IMAGE)
def test_model_registry(
    model_registry_endpoint: Optional[str],
    model_name: Optional[str],
    model_version: Optional[str],
):
    import sys
    import urllib

    from model_registry import ModelRegistry
    from model_registry.exceptions import StoreError

    if not model_registry_endpoint:
        print(f"""
        ########################### INFO ##############################
        # Model Registry endpoint is not provided. Skipping this step #
        ###############################################################
        """)

    try:
        # Extract the port out of the URL because the ModelRegistry client expects those as separate arguments.
        model_registry_api_url_parsed = urllib.parse.urlparse(model_registry_endpoint)
        model_registry_api_url_port = model_registry_api_url_parsed.port

        if model_registry_api_url_port:
            model_registry_api_server_address = model_registry_endpoint.replace(
                model_registry_api_url_parsed.netloc,
                model_registry_api_url_parsed.hostname,
            )
        else:
            if model_registry_api_url_parsed.scheme == "http":
                model_registry_api_url_port = 80
            else:
                model_registry_api_url_port = 443

            model_registry_api_server_address = model_registry_endpoint

        if not model_registry_api_url_parsed.scheme:
            model_registry_api_server_address = (
                "https://" + model_registry_api_server_address
            )

        with open(
            "/var/run/secrets/kubernetes.io/serviceaccount/token", "r"
        ) as token_file:
            token = token_file.readline()

        registry = ModelRegistry(
            server_address=model_registry_api_server_address,
            port=model_registry_api_url_port,
            author="InstructLab Pipeline",
            user_token=token,
        )
        if registry.get_model_version(model_name, model_version) is not None:
            print(f"""
            ###################################################### ERROR ######################################################
            # The version {model_version} for model {model_name} is already registered. You cannot overwrite a model version. #
            ###################################################################################################################
            """)
            sys.exit(1)
    except StoreError as store:
        # The model has no versions registered.
        # Do nothing, just to avoid this exception to return failure
        print(f"""
        ########### INFO ##############
        # Model Registry is available #
        ###############################
        """)
        sys.exit(0)
    except Exception as e:
        print(f"""
        ############# ERROR ###############
        # Model Registry is not available #
        ###################################
        """)
        raise


@dsl.component(base_image=RUNTIME_GENERIC_IMAGE)
def test_training_operator():
    import sys

    from kubernetes import client, config
    from kubernetes.client.rest import ApiException

    with open(
        "/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r"
    ) as namespace_path:
        namespace = namespace_path.readline()
    config.load_incluster_config()

    with client.ApiClient() as api_client:
        api_instance = client.CustomObjectsApi(api_client)

        group = "kubeflow.org"
        version = "v1"
        plural = "pytorchjobs"

        try:
            api_response = api_instance.list_namespaced_custom_object(
                group, version, namespace, plural
            )
            print("""
            ######################### INFO ###########################
            # Kubeflow Training Operator PyTorchJob CRD is available #
            ##########################################################
            """)
        except ApiException as e:
            print("""
            #################################################### ERROR ######################################################################
            # Kubeflow Training Operator PyTorchJob CRD is unavailable. Ensure your OpenShift AI installation has Training Operator enabled #
            #################################################################################################################################
            """)
            sys.exit(1)


@dsl.component(base_image=RUNTIME_GENERIC_IMAGE)
def test_oci_model(output_oci_model_uri: str, output_oci_registry_secret: str):
    import base64
    import json
    import sys

    from kubernetes import client, config
    from kubernetes.client.rest import ApiException

    with open(
        "/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r"
    ) as namespace_path:
        namespace = namespace_path.readline()
    config.load_incluster_config()

    if output_oci_model_uri is None:
        print(f"""
        ############################## INFO ##################################
        # Parameter output_oci_model_uri not provided. Skipping this step... #
        ######################################################################
        """)
        sys.exit(0)

    # Extract from sdg_base_model parameter the registry name
    registry_name = output_oci_model_uri.replace("oci://", "").split("/")[0]

    with client.ApiClient() as api_client:
        core_api = client.CoreV1Api(api_client)
        try:
            secret = core_api.read_namespaced_secret(
                output_oci_registry_secret, namespace
            )
            print(f"Reading secret {output_oci_registry_secret} data...")
            if secret.type == "kubernetes.io/dockerconfigjson":
                # handle authentication if secret provided is kubernetes.io/dockerconfigjson
                docker_config_json = json.loads(
                    base64.b64decode(secret.data[".dockerconfigjson"]).decode("utf-8")
                )
                print(f"""
                ############## INFO #################
                # OCI Secret has auth token present #
                #####################################
                """)
            elif secret.type == "kubernetes.io/dockercfg":
                # handle authentication if secret provided is kubernetes.io/dockercfg
                dockercfg_json = json.loads(
                    base64.b64decode(secret.data[".dockercfg"]).decode("utf-8")
                )
                print(f"""
                ############## INFO #################
                # OCI Secret has auth token present #
                #####################################
                """)
        except ApiException as e:
            print(f"""
            ############################################## ERROR #################################################################
            # Secret {output_oci_registry_secret} does not exist. Ensure you created a secret with this name in namespace {namespace} #
            ######################################################################################################################
            """)
            sys.exit(1)
        except Exception as e:
            print(f"""
            ################## ERROR ##################
            # Failed to check oci model and/or secret #
            ###########################################
            """)
            raise


@dsl.container_component
def test_taxonomy_repo(sdg_repo_url: str):
    return dsl.ContainerSpec(
        RUNTIME_GENERIC_IMAGE,
        ["/bin/sh", "-c"],
        [
            f"""
            # Increase logging verbosity
            set -x &&

            # Set Preferred CA Cert
            if [ -s "$TAXONOMY_CA_CERT_PATH" ]; then
                export GIT_SSL_NO_VERIFY=false
                export GIT_SSL_CAINFO="$TAXONOMY_CA_CERT_PATH"
            elif [ ! -z "$SSL_CERT_DIR" ]; then
                export GIT_SSL_NO_VERIFY=false
                export GIT_SSL_CAPATH="$SSL_CERT_DIR"
            elif [ -s "$SSL_CERT_FILE" ]; then
                export GIT_SSL_NO_VERIFY=false
                export GIT_SSL_CAINFO="$SSL_CERT_FILE"
            fi

            # ls-remote will fail if repo is not valid
            for i in $(seq 1 5);
            do
                git ls-remote {sdg_repo_url} > /dev/null && break
                sleep 5
            done
            """
        ],
    )


@dsl.pipeline(display_name="Prerequisite check")
def prerequisites_check_op(
    sdg_repo_url: str,
    output_oci_registry_secret: str,
    eval_judge_secret: str,
    sdg_teacher_secret: str,
    output_oci_model_uri: str,
    output_model_registry_api_url: str,
    output_model_name: str,
    output_model_version: str,
):
    """
    Pre-validation checks for the InstructLab pipeline.
    """
    import os

    ## Validate judge information
    test_judge_model_op = test_model_connection(secret_name=eval_judge_secret)
    use_config_map_as_volume(
        test_judge_model_op, JUDGE_CONFIG_MAP, mount_path="/tmp/cert"
    )
    test_judge_model_op.set_env_variable(
        "SDG_CA_CERT_PATH", os.path.join("/tmp/cert", "ca.crt")
    )
    test_judge_model_op.set_caching_options(False)

    ## Validate teacher information
    test_teacher_model_op = test_model_connection(secret_name=sdg_teacher_secret)
    use_config_map_as_volume(
        test_teacher_model_op, TEACHER_CONFIG_MAP, mount_path="/tmp/cert"
    )
    test_teacher_model_op.set_env_variable(
        "SDG_CA_CERT_PATH", os.path.join("/tmp/cert", "ca.crt")
    )
    test_teacher_model_op.set_caching_options(False)

    # Validate Model Registry configuration
    test_model_registry_op = test_model_registry(
        model_registry_endpoint=output_model_registry_api_url,
        model_name=output_model_name,
        model_version=output_model_version,
    )
    test_model_registry_op.set_caching_options(False)

    # Validate Training Operator installation
    test_training_operator_op = test_training_operator()
    test_training_operator_op.set_caching_options(False)

    # Validate OCI configuration for pushing the OCI ModelCar
    test_oci_configuration_op = test_oci_model(
        output_oci_model_uri=output_oci_model_uri,
        output_oci_registry_secret=output_oci_registry_secret,
    )
    test_oci_configuration_op.set_caching_options(False)

    # Validate git repository
    test_taxonomy_repo_op = test_taxonomy_repo(sdg_repo_url=sdg_repo_url)
    test_taxonomy_repo_op.set_caching_options(False)
