# type: ignore
# pylint: disable=no-value-for-parameter,import-outside-toplevel,import-error,no-member
from typing import List, Literal, Optional
import click
import typing
from kfp import dsl, compiler
from kfp.kubernetes import (
    use_config_map_as_env,
    use_secret_as_env,
    CreatePVC,
    DeletePVC,
    mount_pvc,
)

# For now, all external models are the same mistral, but won't be always
K8S_NAME = "kfp-model-server"
JUDGE_CONFIG_MAP = "kfp-model-server"
JUDGE_SECRET = "judge-server"
MOCKED_STAGES = ["sdg", "train", "eval"]
PIPELINE_FILE_NAME = "pipeline.yaml"
STANDALONE_TEMPLATE_FILE_NAME = "standalone.tpl"
GENERATED_STANDALONE_FILE_NAME = "standalone.py"
DEFAULT_REPO_URL = "https://github.com/instructlab/taxonomy.git"
KFP_MODEL_SERVER_CM = "sdg/kfp-model-server.yaml"
BASE_MODE = "ibm-granite/granite-7b-base"
MMLU_TASKS_LIST = "mmlu_anatomy,mmlu_astronomy"
MODEL_DTYPE = "bfloat16"
FEW_SHOTS = 5
BATCH_SIZE = 8
MAX_WORKERS = "auto"
MERGE_SYSTEM_USER_MESSAGE = False


def pipeline_wrapper(mock: List[Literal[MOCKED_STAGES]]):
    """Wrapper for KFP pipeline, which allows for mocking individual stages."""

    # Imports for SDG stage
    if mock is not None and "sdg" in mock:
        from sdg.faked import git_clone_op, sdg_op
    else:
        from sdg import git_clone_op, sdg_op

    # Imports for Training stage
    if mock is not None and "train" in mock:
        from training.faked import pytorchjob_manifest_op
        from utils.faked import (
            kubectl_apply_op,
            kubectl_wait_for_op,
            huggingface_importer_op,
            pvc_to_artifact_op,
            pvc_to_model_op,
        )
        from utils import artifact_to_pvc_op
    else:
        from training import data_processing_op, pytorchjob_manifest_op
        from utils import (
            kubectl_apply_op,
            kubectl_wait_for_op,
            artifact_to_pvc_op,
            huggingface_importer_op,
            pvc_to_artifact_op,
            pvc_to_model_op,
        )

    # Imports for MMLU, MT_BENCH stage
    # TODO: Add mock/fake components
    from utils import list_models_in_directory_op
    from eval.mmlu import run_mmlu_op, load_mmlu_results_op
    from eval.mt_bench import run_mt_bench_op, load_mt_bench_results_op

    @dsl.pipeline(
        display_name="InstructLab",
        name="instructlab",
        description="InstructLab pipeline",
    )
    def pipeline(
        num_instructions_to_generate: int = 2,
        repo_url: str = "https://github.com/instructlab/taxonomy.git",
        repo_branch: Optional[str] = None,
        repo_pr: Optional[int] = None,
        storage_class_name: str = "nfs-csi",
        base_model: str = BASE_MODE,
        # minimal subset of MMLU_TASKS
        mmlu_tasks_list: str = MMLU_TASKS_LIST,
        model_dtype: str = MODEL_DTYPE,
        few_shots: int = FEW_SHOTS,
        batch_size: int = BATCH_SIZE,
        max_workers: str = MAX_WORKERS,
        merge_system_user_message: bool = MERGE_SYSTEM_USER_MESSAGE,
        device: str = None,
    ):
        # SDG stage
        git_clone_task = git_clone_op(
            repo_branch=repo_branch,
            repo_pr=repo_pr if repo_pr and repo_pr > 0 else None,
            repo_url=repo_url,
        )

        sdg_task = sdg_op(
            num_instructions_to_generate=num_instructions_to_generate,
            taxonomy=git_clone_task.outputs["taxonomy"],
            repo_branch=repo_branch,
            repo_pr=repo_pr,
        )
        use_config_map_as_env(
            sdg_task, K8S_NAME, dict(endpoint="endpoint", model="model")
        )
        use_secret_as_env(sdg_task, K8S_NAME, {"api_key": "api_key"})

        # Training stage

        # We need to pass storage_class_name as "" to use the default StorageClass, if left empty, KFP uses "standard" StorageClass.
        # 'standard' !=  default StorageClass
        # https://github.com/kubeflow/pipelines/blob/1cded35cf5e93d8c8d32fefbddceb2eed8de9a0a/backend/src/v2/driver/driver.go#L1428-L1436
        # At least we made it a pipeline parameter
        model_pvc_task = CreatePVC(
            pvc_name_suffix="-model-cache",
            access_modes=["ReadWriteMany"],
            size="100Gi",
            storage_class_name=storage_class_name,
        )
        model_to_artifact = huggingface_importer_op(repo_name=base_model)
        model_to_pvc_task = artifact_to_pvc_op(
            data=model_to_artifact.outputs["model"], pvc_path="/model"
        )
        model_to_pvc_task.set_caching_options(False)
        model_to_pvc_task.set_retry(3)
        mount_pvc(
            task=model_to_pvc_task, pvc_name=model_pvc_task.output, mount_path="/model"
        )

        # Data processing
        data_processing_task = data_processing_op(
            sdg=sdg_task.outputs["sdg"], model=model_to_artifact.outputs["model"]
        )

        sdg_input_pvc_task = CreatePVC(
            pvc_name_suffix="-sdg",
            access_modes=["ReadWriteMany"],
            size="1Gi",
            storage_class_name=storage_class_name,
        )
        sdg_to_pvc_task = artifact_to_pvc_op(
            data=data_processing_task.outputs["processed_data"], pvc_path="/data"
        )
        sdg_to_pvc_task.set_caching_options(False)
        mount_pvc(
            task=sdg_to_pvc_task, pvc_name=sdg_input_pvc_task.output, mount_path="/data"
        )

        output_pvc_task = CreatePVC(
            pvc_name_suffix="-output",
            access_modes=["ReadWriteMany"],
            size="100Gi",
            storage_class_name=storage_class_name,
        )

        # Using pvc_create_task.output as PyTorchJob name since dsl.PIPELINE_* global variables do not template/work in KFP v2
        # https://github.com/kubeflow/pipelines/issues/10453
        pytorchjob_manifest_task = pytorchjob_manifest_op(
            model_pvc_name=model_pvc_task.output,
            input_pvc_name=sdg_input_pvc_task.output,
            name_suffix=sdg_input_pvc_task.output,
            output_pvc_name=output_pvc_task.output,
            path_to_model="/input_model/model",
            phase_name="first",
        )
        pytorchjob_manifest_task.set_caching_options(False)

        kubectl_apply_task = kubectl_apply_op(
            manifest=pytorchjob_manifest_task.outputs["manifest"]
        )
        kubectl_apply_task.after(sdg_to_pvc_task, model_to_pvc_task)
        kubectl_apply_task.set_caching_options(False)

        kubectl_wait_task = kubectl_wait_for_op(
            condition="condition=Succeeded",
            kind="pytorchjobs",
            name=pytorchjob_manifest_task.outputs["name"],
        )
        kubectl_wait_task.after(kubectl_apply_task)
        kubectl_wait_task.set_caching_options(False)

        # MMLU Evaluation of models

        models_list_task = list_models_in_directory_op(
            models_folder="/output/model/model/hf_format",
        )
        models_list_task.set_caching_options(False)

        models_list_task.after(kubectl_wait_task)

        mount_pvc(
            task=models_list_task,
            pvc_name=output_pvc_task.output,
            mount_path="/output/model",
        )

        run_mmlu_task = run_mmlu_op(
            models_list=models_list_task.output,
            models_path_prefix="/output/model/hf_format",
            mmlu_tasks_list=mmlu_tasks_list,
            model_dtype=model_dtype,
            few_shots=few_shots,
            batch_size=batch_size,
            device=device,
        )

        run_mmlu_task.set_caching_options(False)

        mount_pvc(
            task=run_mmlu_task, pvc_name=output_pvc_task.output, mount_path="/output"
        )

        load_mmlu_results_task = load_mmlu_results_op(
            mmlu_output=run_mmlu_task.outputs["mmlu_output"],
        )

        run_mmlu_task.set_accelerator_type("nvidia.com/gpu")
        run_mmlu_task.set_accelerator_limit(1)

        #    Run training on MMLU best-model
        #    Run final eval on best scored mt_bench candidate
        #    For now, running mt_bench on same output models as training phase 1
        #    TODO: Another training phase, using the best-model from MMLU as base

        #### Train 2

        pytorchjob_manifest_2_task = pytorchjob_manifest_op(
            model_pvc_name=model_pvc_task.output,
            input_pvc_name=sdg_input_pvc_task.output,
            name_suffix=sdg_input_pvc_task.output,
            output_pvc_name=output_pvc_task.output,
            path_to_model=run_mmlu_task.outputs["best_model"],
            phase_name="second",
        )

        pytorchjob_manifest_2_task.set_caching_options(False)

        kubectl_apply_2_task = kubectl_apply_op(
            manifest=pytorchjob_manifest_2_task.outputs["manifest"]
        )
        kubectl_apply_2_task.after(sdg_to_pvc_task, model_to_pvc_task)
        kubectl_apply_2_task.set_caching_options(False)

        kubectl_wait_2_task = kubectl_wait_for_op(
            condition="condition=Succeeded",
            kind="pytorchjobs",
            name=pytorchjob_manifest_2_task.outputs["name"],
        )
        kubectl_wait_2_task.after(kubectl_apply_2_task)
        kubectl_wait_2_task.set_caching_options(False)

        ###

        models_list_2_task = list_models_in_directory_op(
            models_folder="/output/model/model/hf_format",
        )
        models_list_2_task.set_caching_options(False)

        models_list_2_task.after(kubectl_wait_2_task)

        mount_pvc(
            task=models_list_2_task,
            pvc_name=output_pvc_task.output,
            mount_path="/output/model",
        )

        ###
        run_mt_bench_task = run_mt_bench_op(
            # TODO: make a second models_list_task from the 2nd phase of training
            models_list=models_list_2_task.output,
            models_path_prefix="/output/model/hf_format",
            max_workers=max_workers,
            merge_system_user_message=merge_system_user_message,
            device=device,
        )

        mount_pvc(
            task=run_mt_bench_task,
            pvc_name=output_pvc_task.output,
            mount_path="/output",
        )

        # For now run on same models from same training run as MMLU
        run_mt_bench_task.after(models_list_2_task)

        run_mt_bench_task.set_accelerator_type("nvidia.com/gpu")
        run_mt_bench_task.set_accelerator_limit(1)
        run_mt_bench_task.set_caching_options(False)

        use_config_map_as_env(
            run_mt_bench_task,
            JUDGE_CONFIG_MAP,
            dict(endpoint="JUDGE_ENDPOINT", model="JUDGE_NAME"),
        )

        use_secret_as_env(run_mt_bench_task, JUDGE_SECRET, {"api_key": "JUDGE_API_KEY"})

        # Technically `output_model_task` and `output_data_task` can happen before evaluation,
        # however the PVC can only be mounted once, so, setting these to _after_ so the eval proceeds.
        output_model_task = pvc_to_artifact_op(
            pvc_path="/output/data",
        )
        # output_model_task.after(kubectl_wait_task)
        output_model_task.after(run_mt_bench_task)
        output_model_task.set_caching_options(False)

        mount_pvc(
            task=output_model_task,
            pvc_name=output_pvc_task.output,
            mount_path="/output/data",
        )

        output_data_task = pvc_to_model_op(
            pvc_path="/output/model",
        )
        # output_data_task.after(kubectl_wait_task)
        output_data_task.after(run_mt_bench_task)

        mount_pvc(
            task=output_data_task,
            pvc_name=output_pvc_task.output,
            mount_path="/output/model",
        )

        output_pvc_delete_task = DeletePVC(pvc_name=output_pvc_task.output)
        output_pvc_delete_task.after(output_data_task)

        sdg_pvc_delete_task = DeletePVC(pvc_name=sdg_input_pvc_task.output)
        sdg_pvc_delete_task.after(output_data_task)

        model_pvc_delete_task = DeletePVC(pvc_name=model_pvc_task.output)
        model_pvc_delete_task.after(output_data_task)

        return

    return pipeline


@click.option(
    "--mock",
    type=click.Choice(MOCKED_STAGES, case_sensitive=False),
    help="Mock part of the pipeline",
    multiple=True,
    default=[],
)
@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context, mock):
    if ctx.invoked_subcommand is None:
        generate_pipeline(mock)


def generate_pipeline(mock):
    p = pipeline_wrapper(mock)

    with click.progressbar(length=1, label="Generating pipeline") as bar:
        compiler.Compiler().compile(p, PIPELINE_FILE_NAME)
        bar.update(1)


@cli.command(name="gen-standalone")
def gen_standalone():
    """
    Generates a standalone script that mimics the behavior of the pipeline.

    This function should be used when Kubeflow Pipelines are not available. It will generate a
    script that replicates the pipeline's functionality.

    Example usage: ``` $ python pipeline.py gen-standalone ```
    """
    from jinja2 import Template
    from jinja2.exceptions import TemplateSyntaxError
    import yaml
    from os import path

    click.echo("Generating pipeline YAML file...")
    try:
        generate_pipeline(mock=None)
    except ValueError as e:
        click.echo(f"Error: {e}", err=True)
        raise click.exceptions.Exit(1)

    # Load the YAML pipeline file which contains multiple documents
    with open(PIPELINE_FILE_NAME, "r", encoding="utf-8") as file:
        try:
            documents = list(yaml.safe_load_all(file))
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.exceptions.Exit(1)

    # The list of executor names to extract details from to generate the standalone script
    executors = {
        "exec-data-processing-op": {
            "inputs": {
                "parameterValues": {
                    "max_seq_len": 4096,
                    "max_batch_len": 20000,
                },
                "artifacts": {
                    "sdg": {
                        "artifacts": [
                            {
                                "name": "sdg",
                                "uri": "/input_data/generated",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                    "model": {
                        "artifacts": [
                            {
                                "name": "model",
                                "uri": "/input_model",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                },
            },
            "outputs": {
                "outputFile": "/tmp/kfp_outputs/output_metadata.json",
                "artifacts": {
                    "processed_data": {
                        "artifacts": [
                            {
                                "name": "processed_data",
                                "uri": "/input_data/processed_data",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                },
            },
        },
        "exec-sdg-op": {
            "inputs": {
                "parameterValues": {
                    "num_instructions_to_generate": 2,
                    "repo_branch": "",
                    "repo_pr": "",
                },
                "artifacts": {
                    "taxonomy": {
                        "artifacts": [
                            {
                                "name": "taxonomy",
                                "uri": "/input_data/taxonomy",  # TODO: do not hardcode!!
                            }
                        ]
                    }
                },
            },
            "outputs": {
                "outputFile": "/tmp/kfp_outputs/output_metadata.json",
                "artifacts": {
                    "sdg": {
                        "artifacts": [
                            {
                                "name": "sdg",
                                "uri": "/input_data/generated",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                },
            },
        },
        "exec-git-clone-op": {},
        "exec-huggingface-importer-op": {
            "inputs": {
                "parameterValues": {
                    "repo_name": BASE_MODE,
                },
            },
            "outputs": {
                "outputFile": "/tmp/kfp_outputs/output_metadata.json",
                "artifacts": {
                    "model": {
                        "artifacts": [
                            {
                                "name": "model",
                                "uri": "/input_model",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                },
            },
        },
        "exec-run-mmlu-op": {
            "inputs": {
                "parameterValues": {
                    "models_path_prefix": "/output/model/hf_format",
                    "mmlu_tasks_list": MMLU_TASKS_LIST,
                    "model_dtype": MODEL_DTYPE,
                    "few_shots": FEW_SHOTS,
                    "batch_size": BATCH_SIZE,
                    "models_folder": "/output/model/hf_format",
                },
            },
            "outputs": {
                "outputFile": "/tmp/kfp_outputs/output_metadata.json",
                "artifacts": {
                    "mmlu_output": {
                        "artifacts": [
                            {
                                "name": "mmlu_output",
                                "uri": "/output/mmlu-results.txt",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                },
            },
        },
        "exec-run-mt-bench-op": {
            "inputs": {
                "parameterValues": {
                    "models_path_prefix": "/output/model/hf_format",
                    "merge_system_user_message": MERGE_SYSTEM_USER_MESSAGE,
                    "max_workers": MAX_WORKERS,
                },
            },
            "outputs": {
                "outputFile": "/tmp/kfp_outputs/output_metadata.json",
                "artifacts": {
                    "mt_bench_output": {
                        "artifacts": [
                            {
                                "name": "mt_bench_output",
                                "uri": "/output/mt-bench-results.txt",  # TODO: do not hardcode!!
                            }
                        ]
                    },
                },
            },
        },
    }

    details = {}
    for executor_name, executor_input_param in executors.items():
        try:
            executor_name_camelize = executor_name.replace("-", "_")
            # replace "-" with "_" in executor_name to match the key in the details dictionary
            executor_details = get_executor_details(documents, executor_name)
            if executor_details is not None:
                details[executor_name_camelize + "_image"] = executor_details["image"]
                details[executor_name_camelize + "_command"] = executor_details[
                    "command"
                ]
                details[executor_name_camelize + "_args"] = remove_template_markers(
                    executor_details["args"],
                    executor_name_camelize,
                    executor_input_param,
                )
        except ValueError as e:
            click.echo(f"Error: {e}", err=True)
            raise click.exceptions.Exit(1)

    # Populate the KFP model server ConfigMap
    with open(
        path.join(path.dirname(__file__), KFP_MODEL_SERVER_CM), encoding="utf-8"
    ) as f:
        details["kfp_model_server_cm"] = f.read()

    # Open the template file
    try:
        with open(
            STANDALONE_TEMPLATE_FILE_NAME, "r", encoding="utf-8"
        ) as template_file:
            template_content = template_file.read()
    except FileNotFoundError as e:
        click.echo(
            f"Error: The template file '{STANDALONE_TEMPLATE_FILE_NAME}' was not found.",
            err=True,
        )
        raise click.exceptions.Exit(1) from e
    except IOError as e:
        click.echo(
            f"Error: An I/O error occurred while reading '{STANDALONE_TEMPLATE_FILE_NAME}': {e}",
            err=True,
        )
        raise click.exceptions.Exit(1)

    # Prepare the Jinja2 Template
    try:
        template = Template(template_content)
    except TemplateSyntaxError as e:
        click.echo(
            f"Error: The template file '{STANDALONE_TEMPLATE_FILE_NAME}' contains a syntax error: {e}",
            err=True,
        )
        raise click.exceptions.Exit(1)

    # Render the template with dynamic values
    rendered_code = template.render(details)

    # Write the rendered code to a new Python file
    with open(GENERATED_STANDALONE_FILE_NAME, "w", encoding="utf-8") as output_file:
        output_file.write(rendered_code)

    click.echo(f"Successfully generated '{GENERATED_STANDALONE_FILE_NAME}' script.")


def get_executor_details(
    documents: typing.List[typing.Dict[str, typing.Any]], executor_name: str
) -> dict | None:
    """
    Extracts the command, args, and image of a given executor container from the provided YAML
    documents.

    Args:
        documents (List[Dict[str, Any]]): List of YAML documents loaded as dictionaries.
        executor_name (str): The name of the executor to search for.

    Returns:
        dict: A dictionary containing the 'command', 'args', and 'image' of the executor container
        if found, otherwise raise en error.
    """
    spec = "deploymentSpec"
    deployment_spec_found = False
    for doc in documents:
        deployment_spec = doc.get(spec)
        if not deployment_spec:
            continue
        else:
            deployment_spec_found = True
        for executors_value in deployment_spec.values():
            for executor, executor_value in executors_value.items():
                if executor == executor_name:
                    container = executor_value.get("container", {})
                    if not all(
                        key in container for key in ("command", "args", "image")
                    ):
                        raise ValueError(
                            f"Executor '{executor_name}' does not have the required "
                            "'command', 'args', or 'image' fields."
                        )
                    return {
                        "command": container["command"],
                        "args": container["args"],
                        "image": container["image"],
                    }
        print(f"Executor '{executor_name}' not found in the provided {spec} document.")
        return None
    if not deployment_spec_found:
        raise ValueError(
            "The provided documents do not contain a 'deploymentSpec' key."
        )


def remove_template_markers(
    rendered_code: list, executor_name: str, executor_input_param: str
) -> list:
    """
    Removes the Jinja2 template markers from each element of the rendered code list.

    Args:
        rendered_code (list): The list of rendered code elements containing Jinja2 template markers.

    Returns:
        list: The list of rendered code elements with Jinja2 template markers removed.

    Examples with an executor name of 'exec':
        Input: ["{{$.inputs.parameters['repo_name']}}", "{{$.inputs.parameters['model']}}"]
        Output: ["{exec_repo_name}", "{exec_model}"]

    """
    import re
    import json

    pattern = r"\{\{\$\.inputs\.parameters\['([^']+)'\]\}\}"
    rendered_code = [
        re.sub(pattern, r"{%s_\1}" % executor_name, element)
        for element in rendered_code
    ]

    # TODO: find a better approach
    # Only useful for git_clone_op at the moment
    # additionally remove {{$.outputs.artifacts[\'taxonomy\'].path}}
    pattern = r"\{\{\$\.outputs\.artifacts\['([^']+)'\]\.path\}\}"
    rendered_code = [
        re.sub(pattern, r"{TAXONOMY_PATH}", element) for element in rendered_code
    ]

    # Replace '{{$}}' with input_param
    pattern = r"\{\{\$\}\}"
    rendered_code = [
        re.sub(pattern, json.dumps(executor_input_param), element)
        for element in rendered_code
    ]

    return rendered_code


if __name__ == "__main__":
    cli()
