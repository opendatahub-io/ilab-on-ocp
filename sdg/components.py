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
            CA_CERT_PATH=$TAXONOMY_CA_CERT_PATH
            if [ -s "DSP_TRUSTED_CA_CERT_PATH" ]; then
                CA_CERT_PATH=$DSP_TRUSTED_CA_CERT_PATH
            fi

            # Add TLS Parameters if CA Cert exists and is non-zero size
            ADDITIONAL_CLONE_PARAMS=""
            if [ -s "$CA_CERT_PATH" ]; then
                ADDITIONAL_CLONE_PARAMS="-c http.sslVerify=true -c http.sslCAInfo=$CA_CERT_PATH"
            fi

            # Clone Taxonomy Repo
            git clone $ADDITIONAL_CLONE_PARAMS {repo_url} {taxonomy_path} &&
            cd {taxonomy_path} &&

            # Run additional configuration if TLS certs provided
            if [ -s "$CA_CERT_PATH" ]; then
                git config http.sslVerify true &&
                git config http.sslCAInfo $CA_CERT_PATH
            fi &&

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
    repo_branch: Optional[str],
    repo_pr: Optional[int],
    taxonomy_path: str = "/data/taxonomy",
    sdg_path: str = "/data/sdg",
    sdg_sampling_size: float = 1.0,
):
    import os
    import shutil
    import tempfile

    import instructlab.sdg
    import openai
    import xdg_base_dirs
    import yaml

    api_key = os.getenv("api_key")
    model = os.getenv("model")
    endpoint = os.getenv("endpoint")

    sdg_ca_cert_path = os.getenv("SDG_CA_CERT_PATH")
    dsp_ca_cert_path = os.getenv("DSP_TRUSTED_CA_CERT_PATH")

    dsp_ca_exists = os.path.isfile(dsp_ca_cert_path) and (os.path.getsize(dsp_ca_cert_path) > 0)
    sdg_ca_exists = os.path.isfile(sdg_ca_cert_path) and (os.path.getsize(sdg_ca_cert_path) > 0)

    use_tls = (dsp_ca_exists or sdg_ca_exists)

    if use_tls:
        import httpx

        ca_cert_path = dsp_ca_cert_path if dsp_ca_exists else sdg_ca_cert_path
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
            model_name=model,
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
                for d in data_dirs:
                    pipeline_path = os.path.join(d, "pipelines", pipeline)
                    if os.path.exists(pipeline_path):
                        shutil.copytree(
                            pipeline_path,
                            temp_pipeline_dir,
                            dirs_exist_ok=True,
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
                        model_name=model,
                        pipeline=pipeline,
                        chunk_word_count=1000,
                        server_ctx_size=4096,
                    )
                except Exception as e:
                    print(f"Failed to set precomputed skills data ratio: {e}")
                    raise


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
