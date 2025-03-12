# type: ignore
# pylint: disable=import-outside-toplevel,import-error
from typing import Optional

from kfp import dsl

from utils.consts import RHELAI_IMAGE, TOOLBOX_IMAGE


@dsl.container_component
def git_clone_op(
    repo_branch: str,
    repo_pr: Optional[int],
    repo_url: Optional[str],
    taxonomy_path: str = "/data/taxonomy",
):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
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

            # Clone Taxonomy Repo
            git clone {repo_url} {taxonomy_path} &&
            cd {taxonomy_path} &&

            # Checkout and use taxonomy repo branch or PR if specified
            if [ -n "{repo_branch}" ]; then
                git fetch origin {repo_branch} && git checkout {repo_branch};
            elif [ -n "{repo_pr}" ] && [ {repo_pr} -gt 0 ]; then
                git fetch origin pull/{repo_pr}/head:{repo_pr} && git checkout {repo_pr};
            fi
            """
        ],
    )


@dsl.component(base_image=RHELAI_IMAGE, install_kfp_package=False)
def sdg_op(
    num_instructions_to_generate: int,
    pipeline: str,
    tokenizer_model: dsl.Input[dsl.Model],
    repo_branch: Optional[str],
    repo_pr: Optional[int],
    taxonomy_path: str = "/data/taxonomy",
    sdg_path: str = "/data/sdg",
    sdg_sampling_size: float = 1.0,
    sdg_secret_name: str = None,
    taxonomy_repo_secret: str = None,
    repo_url: str = None,
):
    import base64
    import os
    import os.path
    import re
    import shutil
    import subprocess
    import tempfile
    import urllib.parse

    import instructlab.sdg
    import openai
    import requests
    import xdg_base_dirs
    import yaml

    REQUEST_TIMEOUT = 30  # seconds

    def fetch_secret(secret_name, keys):
        # Kubernetes API server inside the cluster
        K8S_API_SERVER = "https://kubernetes.default.svc"
        NAMESPACE_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/namespace"
        TOKEN_PATH = "/var/run/secrets/kubernetes.io/serviceaccount/token"

        # Fetch namespace
        try:
            with open(NAMESPACE_PATH, "r") as f:
                namespace = f.read().strip()
        except FileNotFoundError:
            raise RuntimeError("Error reading namespace")

        # Fetch service account token
        try:
            with open(TOKEN_PATH, "r") as f:
                token = f.read().strip()
        except FileNotFoundError:
            raise RuntimeError("Error reading service account token")

        # Fetch secret
        headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
        verify_tls = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        url = f"{K8S_API_SERVER}/api/v1/namespaces/{namespace}/secrets/{secret_name}"
        response = requests.get(
            url, headers=headers, verify=verify_tls, timeout=REQUEST_TIMEOUT
        )

        if response.status_code == 200:
            print(f"Successfully fetched secret {secret_name}")
            secret_data = response.json().get("data", {})
            values = []
            for key in keys:
                if key in secret_data:
                    values.append(base64.b64decode(secret_data[key]).decode())
            return values
        else:
            raise RuntimeError(
                f"Error fetching secret: {response.status_code} {response.text}"
            )

    # Configure Git Credentials (if provided) and environment

    def exec_cmd(cmd, **kwarg):
        if "stdout" in kwarg or "stderr" in kwarg:
            # If stdout or stderr is explicitly set, remove capture_output to avoid conflicts
            res = subprocess.run(cmd, text=True, **kwarg)
        else:
            # Default behavior (captures output)
            res = subprocess.run(cmd, text=True, capture_output=True, **kwarg)
        if res.stdout:
            print("STDOUT:", res.stdout)
        if res.stderr:
            print("STDERR:", res.stderr)
        if res.returncode != 0:
            raise RuntimeError(f"CMD {cmd} failed with error code: {res.returncode}")
        print(f"Command {cmd} succeeded.")

    def is_ssh(uri: str) -> bool:
        """Checks if a given Git URI is an SSH-based URL."""
        ssh_patterns = [
            r"^git@[\w.-]+:.+",
            r"^ssh://.+",
        ]
        return any(re.match(pattern, uri) for pattern in ssh_patterns)

    def get_git_host(repo_url):
        """Extracts the Git host (e.g., github.com, gitlab.com) from an SSH repository URL."""
        match = re.match(r"git@([\w.-]+):", repo_url)
        if match:
            return match.group(1)  # Extracted host
        raise ValueError(f"Invalid SSH repository URL: {repo_url}")

    tokenizer_model_path = tokenizer_model.path
    if tokenizer_model_path.startswith("oci://"):
        # Handle where the KFP SDK is <2.12.0.
        escaped_uri = tokenizer_model_path[len("oci://") :].replace("/", "\\/")
        tokenizer_model_path = os.path.join("/oci", escaped_uri, "models")

    # A hack because InstructLab assumes the value for model_name is a valid path and the name of the model.
    os.symlink(tokenizer_model_path, os.path.join(tempfile.gettempdir(), "mixtral"))
    os.chdir(tempfile.gettempdir())

    if not taxonomy_repo_secret:
        username = os.getenv("GIT_USERNAME")
        token = os.getenv("GIT_TOKEN")
        ssh_key = os.getenv("GIT_SSH_KEY")
    else:
        print("SDG Repo secret specified, fetching...")
        username, token, ssh_key = fetch_secret(
            taxonomy_repo_secret, ["GIT_USERNAME", "GIT_TOKEN", "GIT_SSH_KEY"]
        )
        print("SDG Repo secret data retrieved.")

    # Whether not provided via env or secret
    # Assume the repo is public
    if not username or ssh_key:
        print("No credentials provided for taxonomy repo, assuming public repo...")

    ca_cert_path = os.getenv("SDG_CA_CERT_PATH")
    env = os.environ.copy()

    # Todo(HumairAK): should be platform cert
    # Set custom CA certificate if provided
    if ca_cert_path:
        print(f"SSL CA Info detected. ca cert path: {ca_cert_path}")
        env["GIT_SSL_CAINFO"] = ca_cert_path
        # Consume this in the process execution environment
        # This is required for read_taxonomy calls which
        # Perform nested calls to git clones.
        os.environ["GIT_SSL_CAINFO"] = ca_cert_path

    git_credentials_path = ""
    ssh_key_path = ""
    # Username/PAT takes precedence over ssh
    if username and token:
        print("Configuring Git Credentials...")
        # Parse the domain from the repository URL
        parsed_url = urllib.parse.urlparse(repo_url)
        git_server = parsed_url.netloc

        # Set up Git credential helper
        exec_cmd(["git", "config", "--global", "credential.helper", "store"], env=env)

        # Save credentials dynamically for any Git server
        git_credentials_directory = os.path.expanduser("~/.git")
        # Ensure the ~/.git directory exists
        os.makedirs(git_credentials_directory, mode=0o700, exist_ok=True)

        git_credentials_path = f"{git_credentials_directory}/.git-credentials"
        with open(git_credentials_path, "w") as f:
            f.write(f"https://{username}:{token}@{git_server}\n")

        os.chmod(git_credentials_path, 0o600)
        exec_cmd(
            [
                "git",
                "config",
                "--global",
                "credential.helper",
                f"store --file {git_credentials_path}",
            ],
            env=env,
        )

        print("Git Credentials configured.")

    # Handle SSH authentication
    elif is_ssh(repo_url):
        ssh_dir = os.path.expanduser("~/.ssh")
        # Ensure the ~/.ssh directory exists
        os.makedirs(ssh_dir, mode=0o700, exist_ok=True)

        # Preemptively add the key to avoid first use prompt.
        git_host = get_git_host(repo_url)
        print(f"Using Git host: {git_host}")
        exec_cmd(
            ["ssh-keyscan", git_host],
            stdout=open(os.path.expanduser("~/.ssh/known_hosts"), "a"),
        )

        # A repo can rarely support anonymous ssh access (rare)
        # So we conditionally check for the key.
        if ssh_key:
            print("Configuring SSH authentication for Git...")
            # Write the SSH key to a temporary file
            with tempfile.NamedTemporaryFile(
                delete=False, mode="w", prefix="ssh_key_", dir=ssh_dir, suffix=".pem"
            ) as ssh_key_file:
                ssh_key_file.write(ssh_key)
                ssh_key_path = ssh_key_file.name
            # Ensure owner has r/w only, SSH may refuse
            # keys if the file is too open.
            os.chmod(ssh_key_path, 0o600)
            # Explicitly direct Git to always use this SSH key
            exec_cmd(
                [
                    "git",
                    "config",
                    "--global",
                    "core.sshCommand",
                    f"ssh -i {ssh_key_path}",
                ]
            )
            print(
                f"Git SSH authentication configured using temporary key at {ssh_key_path}."
            )

    if not repo_url or not taxonomy_path:
        raise RuntimeError(
            "Missing either repo_url or taxonomy_path, cannot proceed with cloning."
        )

    # Handle retries where the repo is already cloned on the PVC
    if os.path.exists(taxonomy_path):
        shutil.rmtree(taxonomy_path)

    # Clone the repository
    exec_cmd(["git", "clone", "-v", repo_url, taxonomy_path], env=env)
    print("Taxonomy repo cloned executed successfully!")
    if repo_branch:
        exec_cmd(["git", "checkout", repo_branch], cwd=taxonomy_path, env=env)
    elif repo_pr:
        # Fetch pull request head
        exec_cmd(
            ["git", "fetch", "origin", f"pull/{repo_pr}/head:pr-{repo_pr}"],
            cwd=taxonomy_path,
            env=env,
        )
        exec_cmd(["git", "checkout", repo_branch], cwd=taxonomy_path, env=env)

    if sdg_secret_name is None:
        api_key = os.getenv("api_key")
        endpoint = os.getenv("endpoint")
    else:
        print("SDG Teacher secret specified, fetching...")
        api_key, endpoint = fetch_secret(sdg_secret_name, ["api_token", "endpoint"])
        print("SDG Teacher secret data retrieved.")

    sdg_ca_cert_path = os.getenv("SDG_CA_CERT_PATH")
    dsp_ca_cert_path = os.getenv("SSL_CERT_FILE")
    dsp_ca_cert_dir = os.getenv("SSL_CERT_DIR")

    dsp_cert_dir_defined = dsp_ca_cert_dir is not None
    dsp_ca_exists = (
        dsp_ca_cert_path is not None
        and os.path.isfile(dsp_ca_cert_path)
        and (os.path.getsize(dsp_ca_cert_path) > 0)
    )
    sdg_ca_exists = (
        sdg_ca_cert_path is not None
        and os.path.isfile(sdg_ca_cert_path)
        and (os.path.getsize(sdg_ca_cert_path) > 0)
    )

    use_tls = dsp_cert_dir_defined or dsp_ca_exists or sdg_ca_exists

    if use_tls:
        import httpx

        # Use SDG CA Cert if explicitly defined, otherwise use system default CA Certs
        ca_cert_path = sdg_ca_cert_path if sdg_ca_exists else True
        custom_http_client = httpx.Client(verify=ca_cert_path)
        client = openai.OpenAI(
            base_url=endpoint, api_key=api_key, http_client=custom_http_client
        )
    else:
        client = openai.OpenAI(base_url=endpoint, api_key=api_key)

    taxonomy_base = "main" if repo_branch or (repo_pr and int(repo_pr) > 0) else "empty"

    print("Generating synthetic dataset for:")
    print()
    print(
        instructlab.sdg.utils.taxonomy.read_taxonomy(
            taxonomy_path, taxonomy_base, document_output_dir=f"{sdg_path}/documents"
        )
    )

    # Generate synthetic dataset
    # 1.0 is the default size
    if sdg_sampling_size == 1.0:
        # generate_data has a magic word for its taxonomy_base argument - 'empty'
        # it allows generating from the whole repo, see:
        # https://github.com/instructlab/sdg/blob/c6a9e74a1618b1077cd38e713b8aaed8b7c0c8ce/src/instructlab/sdg/utils/taxonomy.py#L230
        instructlab.sdg.generate_data(
            client=client,
            num_instructions_to_generate=num_instructions_to_generate,
            output_dir=sdg_path,
            taxonomy=taxonomy_path,
            taxonomy_base=taxonomy_base,
            model_name="mixtral",
            pipeline=pipeline,
            chunk_word_count=1000,
            server_ctx_size=4096,
        )
    # Tweak precomputed skills data ratio if needed
    else:
        skills_recipe = "/usr/share/instructlab/sdg/default_data_recipes/skills.yaml"

        def set_precomputed_skills_data_ratio(sampling_size: float, skills_recipe: str):
            if os.path.exists(skills_recipe):
                with open(skills_recipe, "r", encoding="utf-8") as file:
                    skills_yaml = yaml.load(file, Loader=yaml.Loader)

                skills_yaml["datasets"][0]["sampling_size"] = sampling_size

                with open(skills_recipe, "w", encoding="utf-8") as file:
                    yaml.dump(skills_yaml, file)

        try:
            set_precomputed_skills_data_ratio(
                sampling_size=sdg_sampling_size, skills_recipe=skills_recipe
            )
        except PermissionError:
            # TODO(mprahl): When upgrading to RHEL AI 1.4, replace all this with:
            # https://github.com/instructlab/sdg/blob/v0.7.1/docs/examples/mix_datasets/example_mixing.py
            print("Failed to set precomputed skills data ratio: Permission denied")
            print("Attempting to move default data recipes to temporary directory")

            # Create a temporary directory
            with tempfile.TemporaryDirectory() as temp_dir:
                # Create a default_data_recipes directory
                temp_dir = os.path.join(temp_dir, "default_data_recipes")
                os.mkdir(temp_dir)

                # Copy default_data_recipes/skills.yaml to the temporary directory
                shutil.copy(skills_recipe, temp_dir)

                # Also copy the current pipeline directory to the temporary directory - it's a small
                # directory like 28KB
                # This isn't needed if the pipeline is either "full" or "simple" but it's future-proofing
                data_dirs = [
                    os.path.join(str(dir), "instructlab", "sdg")
                    for dir in xdg_base_dirs.xdg_data_dirs()
                ]
                temp_pipeline_dir = os.path.join(temp_dir, "pipeline")
                os.mkdir(temp_pipeline_dir)
                temp_models_dir = os.path.join(temp_dir, "instructlab", "sdg", "models")
                os.makedirs(temp_models_dir, exist_ok=True)

                for d in data_dirs:
                    pipeline_path = os.path.join(d, "pipelines", pipeline)
                    if os.path.exists(pipeline_path):
                        shutil.copytree(
                            pipeline_path,
                            temp_pipeline_dir,
                            dirs_exist_ok=True,
                        )
                        break

                # The docling SDG model is also needed, so just copy the models config which has paths to the
                # default models.
                for d in data_dirs:
                    models_config_path = os.path.join(d, "models", "config.yaml")
                    if os.path.exists(models_config_path):
                        shutil.copy(
                            models_config_path,
                            os.path.join(temp_models_dir, "config.yaml"),
                        )
                        break

                # Build new skills.yaml path
                new_skills_recipe = os.path.join(temp_dir, "skills.yaml")
                print(f"New skills recipe path: {new_skills_recipe}")

                # Override XDG_DATA_DIRS with the temporary directory
                # This allows SDG to read the new skills.yaml since it's looking into XDG_DATA_DIRS
                # and looks for a default_data_recipes directory with a skills.yaml file
                os.environ["XDG_DATA_DIRS"] = f"{temp_dir}"

                # Try to set the precomputed skills data ratio again
                try:
                    set_precomputed_skills_data_ratio(
                        sampling_size=sdg_sampling_size, skills_recipe=new_skills_recipe
                    )
                    print(
                        f"Successfully set precomputed skills data ratio to {sdg_sampling_size}"
                    )

                    # generate_data has a magic word for its taxonomy_base argument - 'empty'
                    # it allows generating from the whole repo, see:
                    # https://github.com/instructlab/sdg/blob/c6a9e74a1618b1077cd38e713b8aaed8b7c0c8ce/src/instructlab/sdg/utils/taxonomy.py#L230
                    instructlab.sdg.generate_data(
                        client=client,
                        num_instructions_to_generate=num_instructions_to_generate,
                        output_dir=sdg_path,
                        taxonomy=taxonomy_path,
                        taxonomy_base=taxonomy_base,
                        model_name="mixtral",
                        pipeline=pipeline,
                        chunk_word_count=1000,
                        server_ctx_size=4096,
                    )
                except Exception as e:
                    print(f"Failed to set precomputed skills data ratio: {e}")
                    raise

    # Cleanup git configurations
    if git_credentials_path and os.path.exists(git_credentials_path):
        os.remove(git_credentials_path)
        print(f"{git_credentials_path} deleted successfully")
    if ssh_key_path and os.path.exists(ssh_key_path):
        os.remove(ssh_key_path)
        print(f"{ssh_key_path} deleted successfully")


@dsl.container_component
def taxonomy_to_artifact_op(
    taxonomy: dsl.Output[dsl.Dataset], pvc_path: str = "/data/taxonomy"
):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {taxonomy.path}"],
    )


@dsl.container_component
def sdg_to_artifact_op(sdg: dsl.Output[dsl.Dataset], pvc_path: str = "/data/sdg"):
    return dsl.ContainerSpec(
        TOOLBOX_IMAGE,
        ["/bin/sh", "-c"],
        [f"cp -r {pvc_path} {sdg.path}"],
    )
