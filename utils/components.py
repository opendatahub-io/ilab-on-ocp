# type: ignore

from kfp import dsl
from kfp.kubernetes import (
    use_config_map_as_env,
    use_config_map_as_volume,
    use_secret_as_env,
    use_secret_as_volume,
)

from standalone.standalone import sdg_data_fetch

from .consts import PYTHON_IMAGE, RHELAI_IMAGE, TOOLBOX_IMAGE


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


@dsl.container_component
def pvc_to_model_op(model: dsl.Output[dsl.Model], pvc_path: str):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {model.path}"],
    )


@dsl.container_component
def model_to_pvc_op(model: dsl.Input[dsl.Model], pvc_path: str = "/model"):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {model.path}/* {pvc_path}"],
    )


@dsl.container_component
def ilab_importer_op(repository: str, release: str, base_model: dsl.Output[dsl.Model]):
    return dsl.ContainerSpec(
        RHELAI_IMAGE,
        ["/bin/sh", "-c"],
        [
            f"ilab --config=DEFAULT model download --repository {repository} --release {release} --model-dir {base_model.path}"
        ],
    )


@dsl.component(base_image=PYTHON_IMAGE)
def test_judge_teacher_models(cm_name: str, secret_name: str):
    import base64
    import json
    import os
    import sys

    import requests
    from kubernetes import client
    from kubernetes.client.rest import ApiException

    sa_path = "/var/run/secrets/kubernetes.io/serviceaccount"
    configuration = client.Configuration()
    configuration.api_key["authorization"] = open(f"{sa_path}/token").readline()
    configuration.api_key_prefix["authorization"] = "Bearer"
    configuration.host = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}"
    configuration.ssl_ca_cert = f"{sa_path}/ca.crt"

    model_endpoint = ""
    model_name = ""
    model_api_key = ""
    namespace = open(f"{sa_path}/namespace").readline()

    with client.ApiClient(configuration) as api_client:
        core_api = client.CoreV1Api(api_client)

        try:
            config_map = core_api.read_namespaced_config_map(cm_name, namespace)
            print(f"Reading configmap {cm_name} data...")
            model_endpoint = config_map.data["endpoint"]
            model_name = config_map.data["model"]
        except ApiException as e:
            print(f"""
            ############################################ ERROR ###########################################################
            # Configmap {cm_name} does not exist. Ensure you created a configmap with this name in namespace {namespace} #
            ##############################################################################################################
            """)
            sys.exit(1)

        try:
            secret = core_api.read_namespaced_secret(secret_name, namespace)
            print(f"Reading secret {secret_name} data...")
            model_api_key = base64.b64decode(secret.data["api_key"]).decode("utf-8")
        except ApiException as e:
            print(f"""
            ############################################## ERROR #######################################################
            # Secret {secret_name} does not exist. Ensure you created a secret with this name in namespace {namespace} #
            ############################################################################################################
            """)
            sys.exit(1)

    request_auth = {"Authorization": f"Bearer {model_api_key}"}
    request_body = {
        "model": model_name,
        "messages": [{"role": "user", "content": "tell me a funny joke."}],
    }
    resp = requests.post(
        f"{model_endpoint}/chat/completions",
        headers=request_auth,
        data=json.dumps(request_body),
        verify=os.environ["SDG_CA_CERT_PATH"],
    )
    if resp.status_code != 200:
        print(f"""
        ############################################ ERROR ####################################################
        # Model Server {model_name} is unavailable. Ensure the model is up and it is ready to serve requests. #
        #######################################################################################################
        """)
        sys.exit(1)
    else:
        print(f"""
        ################### INFO #######################
        # Model Server {model_name} is up and running. #
        ################################################
        """)


@dsl.component(
    base_image=PYTHON_IMAGE,
    packages_to_install=["model-registry==0.2.13", "kserve==0.13"],
)
def test_model_registry(model_registry_endpoint: str):
    from model_registry import ModelRegistry

    registry = ModelRegistry(
        server_address=model_registry_endpoint,
        author="ilab pipeline",
        is_secure=False,
        user_token=open(
            "/var/run/secrets/kubernetes.io/serviceaccount/token"
        ).readline(),
    )
    # This line should enforce pipeline to hit MR endpoint
    if len(registry.get_registered_models().page_size(1)._next_page()) >= 0:
        print(f"""
        ########### INFO ##############
        # Model Registry is available #
        ###############################
        """)


@dsl.component(base_image=PYTHON_IMAGE)
def test_training_operator():
    import os
    import sys

    from kubernetes import client
    from kubernetes.client.rest import ApiException

    sa_path = "/var/run/secrets/kubernetes.io/serviceaccount"
    configuration = client.Configuration()
    configuration.api_key["authorization"] = open(f"{sa_path}/token").readline()
    configuration.api_key_prefix["authorization"] = "Bearer"
    configuration.host = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}"
    configuration.ssl_ca_cert = f"{sa_path}/ca.crt"
    namespace = open(f"{sa_path}/namespace").readline()

    with client.ApiClient(configuration) as api_client:
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


@dsl.component(base_image=PYTHON_IMAGE)
def test_oci_model(sdg_base_model: str, sdg_oci_docker_secret: str):
    import base64
    import json
    import os
    import sys

    from kubernetes import client
    from kubernetes.client.rest import ApiException

    sa_path = "/var/run/secrets/kubernetes.io/serviceaccount"
    configuration = client.Configuration()
    configuration.api_key["authorization"] = open(f"{sa_path}/token").readline()
    configuration.api_key_prefix["authorization"] = "Bearer"
    configuration.host = f"https://{os.environ['KUBERNETES_SERVICE_HOST']}"
    configuration.ssl_ca_cert = f"{sa_path}/ca.crt"
    namespace = open(f"{sa_path}/namespace").readline()

    if not sdg_base_model.startswith("oci://"):
        # If SDG Model Base is not an OCI image, just inform user and quit
        print("""
        #################### INFO ###########################
        # Model is not OCI-compliant. Skipping this step... #
        #####################################################
        """)
        sys.exit(0)

    # Extract from sdg_base_model parameter the registry name
    registry_name = sdg_base_model.replace("oci://", "").split("/")[0]

    with client.ApiClient(configuration) as api_client:
        core_api = client.CoreV1Api(api_client)
        try:
            secret = core_api.read_namespaced_secret(sdg_oci_docker_secret, namespace)
            print(f"Reading secret {sdg_oci_docker_secret} data...")
            if secret.type == "kubernetes.io/dockerconfigjson":
                # handle authentication if secret provided is kubernetes.io/dockerconfigjson
                docker_config_json = json.loads(
                    base64.b64decode(secret.data[".dockerconfigjson"]).decode("utf-8")
                )
                if registry_name not in docker_config_json["auths"]:
                    print(f"""
                    ########################################################## ERROR ########################################################################################
                    # OCI Secret {sdg_oci_docker_secret} does not have an auth token present for {registry_name}. Ensure that the secret provided has the proper auth token #
                    #########################################################################################################################################################
                    """)
                    sys.exit(1)
                print(f"OCI Secret has auth token present for {registry_name}")
            elif secret.type == "kubernetes.io/dockercfg":
                # handle authentication if secret provided is kubernetes.io/dockercfg
                dockercfg_json = json.loads(
                    base64.b64decode(secret.data[".dockercfg"]).decode("utf-8")
                )
                if registry_name not in docker_config_json.keys():
                    print(f"""
                    ################################################################## ERROR ################################################################################
                    # OCI Secret {sdg_oci_docker_secret} does not have an auth token present for {registry_name}. Ensure that the secret provided has the proper auth token #
                    #########################################################################################################################################################
                    """)
                    sys.exit(1)
                print(f"""
                ######################## INFO ###########################
                # OCI Secret has auth token present for {registry_name} #
                #########################################################
                """)
        except ApiException as e:
            print(f"""
            ############################################## ERROR #################################################################
            # Secret {sdg_oci_docker_secret} does not exist. Ensure you created a secret with this name in namespace {namespace} #
            ######################################################################################################################
            """)
            sys.exit(1)


@dsl.container_component
def test_taxonomy_repo(sdg_repo_url: str):
    return dsl.ContainerSpec(
        PYTHON_IMAGE,
        ["/bin/sh", "-c"],
        [
            f"""
            # Increase logging verbosity
            set -x &&

            # Add TLS Parameters if CA Cert exists and is non-zero size
            ADDITIONAL_CLONE_PARAMS=""
            if [ -s "$TAXONOMY_CA_CERT_PATH" ]; then
                ADDITIONAL_CLONE_PARAMS="-c http.sslVerify=true -c http.sslCAInfo=$TAXONOMY_CA_CERT_PATH"
            fi

            # ls-remote will fail if repo is not valid
            git ls-remote {sdg_repo_url} > /dev/null;
            """
        ],
    )


@dsl.pipeline(display_name="Pre-requisite check")
def pre_requisites_check_op(
    sdg_repo_url: str,
    sdg_base_model: str,
    sdg_oci_secret: str,
    judge_cm_name: str,
    judge_secret_name: str,
    teacher_cm_name: str,
    teacher_secret_name: str,
    model_registry_endpoint: str,
):
    """
    Pre-validation checks for the InstructLab pipeline.
    """
    import os

    # TODO: Is it required to disable caching for all validation steps?
    ## Validate judge information
    test_judge_model_op = test_judge_teacher_models(
        cm_name=judge_cm_name, secret_name=judge_secret_name
    )

    use_config_map_as_env(
        test_judge_model_op, "judge-server", dict(endpoint="endpoint", model="model")
    )
    use_secret_as_env(test_judge_model_op, "judge-server", {"api_key": "api_key"})
    use_config_map_as_volume(
        test_judge_model_op, "judge-server", mount_path="/tmp/cert"
    )
    test_judge_model_op.set_env_variable(
        "SDG_CA_CERT_PATH", os.path.join("/tmp/cert", "ca.crt")
    )
    test_judge_model_op.set_caching_options(False)

    ## Validate teacher information
    test_teacher_model_op = test_judge_teacher_models(
        cm_name=teacher_cm_name, secret_name=teacher_secret_name
    )

    use_config_map_as_env(
        test_teacher_model_op,
        "teacher-server",
        dict(endpoint="endpoint", model="model"),
    )
    use_secret_as_env(test_teacher_model_op, "teacher-server", {"api_key": "api_key"})
    use_config_map_as_volume(
        test_teacher_model_op, "teacher-server", mount_path="/tmp/cert"
    )
    test_teacher_model_op.set_env_variable(
        "SDG_CA_CERT_PATH", os.path.join("/tmp/cert", "ca.crt")
    )
    test_teacher_model_op.set_caching_options(False)

    test_model_registry_op = test_model_registry(
        model_registry_endpoint=model_registry_endpoint
    )
    test_model_registry_op.set_caching_options(False)

    test_training_operator_op = test_training_operator()
    test_training_operator_op.set_caching_options(False)

    test_oci_configuration_op = test_oci_model(
        sdg_base_model=sdg_base_model, sdg_oci_docker_secret=sdg_oci_secret
    )
    test_oci_configuration_op.set_caching_options(False)

    test_taxonomy_repo_op = test_taxonomy_repo(sdg_repo_url=sdg_repo_url)
    test_taxonomy_repo_op.set_caching_options(False)
