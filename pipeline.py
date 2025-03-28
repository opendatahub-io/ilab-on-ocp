# type: ignore
# pylint: disable=no-value-for-parameter,import-outside-toplevel,no-member

from typing import Optional

import click
from kfp import compiler, dsl
from kfp.kubernetes import (
    CreatePVC,
    DeletePVC,
    mount_pvc,
    use_secret_as_env,
    use_secret_as_volume,
)

from eval import generate_metrics_report_op, run_final_eval_op, run_mt_bench_op
from sdg import (
    sdg_op,
    sdg_to_artifact_op,
    taxonomy_to_artifact_op,
)
from training import (
    data_processing_op,
    knowledge_processed_data_to_artifact_op,
    pytorch_job_launcher_op,
    skills_processed_data_to_artifact_op,
)
from utils import (
    ilab_importer_op,
    model_to_pvc_op,
    pvc_to_mmlu_branch_op,
    pvc_to_mt_bench_branch_op,
    pvc_to_mt_bench_op,
    upload_model_op,
)
from utils.components import prerequisites_check_op
from utils.consts import (
    RHELAI_IMAGE,
    RUNTIME_GENERIC_IMAGE,
)

PIPELINE_FILE_NAME = "pipeline.yaml"
IMPORTER_PIPELINE_FILE_NAME = "importer-pipeline.yaml"
DEFAULT_REPO_URL = "https://github.com/instructlab/taxonomy.git"


@dsl.pipeline(
    display_name="InstructLab",
    name="instructlab",
    description="InstructLab pipeline",
)
def ilab_pipeline(
    sdg_base_model: str,
    # Model output
    output_oci_model_uri: str = "",
    output_oci_registry_secret: str = None,
    output_model_name: str = None,
    output_model_version: str = None,
    output_model_registry_name: str = None,
    output_model_registry_api_url: str = None,
    output_modelcar_base_image: str = "registry.access.redhat.com/ubi9-micro:latest",
    # SDG phase
    sdg_repo_url: str = None,
    sdg_repo_secret: str = "taxonomy-repo-secret",
    sdg_repo_branch: Optional[str] = None,
    sdg_repo_pr: Optional[
        int
    ] = None,  # FIXME: https://issues.redhat.com/browse/RHOAIRFE-467
    sdg_teacher_secret: str = "teacher-secret",
    sdg_scale_factor: int = 30,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L125
    sdg_pipeline: str = "/usr/share/instructlab/sdg/pipelines/agentic",  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L122
    sdg_max_batch_len: int = 5000,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L334
    sdg_sample_size: float = 1.0,  # FIXME: Not present in default config. Not configurable upstream at this point, capability added via https://github.com/instructlab/sdg/pull/432
    sdg_batch_size: int = 128,
    sdg_num_workers: int = 2,
    # Training phase
    train_tolerations: Optional[list] = None,
    train_node_selectors: Optional[dict] = None,
    train_gpu_identifier: str = "nvidia.com/gpu",
    train_gpu_per_worker: int = 2,  # FIXME: Not present in default config. Arbitrary value chosen to demonstrate multi-node multi-gpu capabilities. Needs proper reference architecture justification.
    train_cpu_per_worker: str = "2",  # FIXME: Not present in default config. Arbitrary value chosen to demonstrate multi-node multi-gpu capabilities. Needs proper reference architecture justification.
    train_memory_per_worker: str = "2Gi",  # FIXME: Not present in default config. Arbitrary value chosen to demonstrate multi-node multi-gpu capabilities. Needs proper reference architecture justification.
    train_num_workers: int = 2,  # FIXME: Not present in default config. Arbitrary value chosen to demonstrate multi-node multi-gpu capabilities. Needs proper reference architecture justification.
    train_num_epochs_phase_1: int = 7,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L364
    train_num_epochs_phase_2: int = 10,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L377
    train_effective_batch_size_phase_1: int = 128,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L357
    train_effective_batch_size_phase_2: int = 3840,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L371
    train_learning_rate_phase_1: float = 2e-05,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L360
    train_learning_rate_phase_2: float = 6e-06,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L374
    train_num_warmup_steps_phase_1: int = 1000,  # https://github.com/instructlab/training/blob/v0.6.1/src/instructlab/training/main_ds.py#L874
    train_num_warmup_steps_phase_2: int = 1000,  # https://github.com/instructlab/training/blob/v0.6.1/src/instructlab/training/main_ds.py#L874
    train_save_samples: int = 250000,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L393
    train_max_batch_len: int = 5000,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L334
    train_seed: int = 42,  # https://github.com/instructlab/training/blob/v0.6.1/src/instructlab/training/main_ds.py#L901
    # MT Bench
    mt_bench_max_workers: str = "auto",  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L74
    mt_bench_merge_system_user_message: bool = False,  # https://github.com/instructlab/instructlab/blob/v0.21.2/src/instructlab/model/evaluate.py#L474
    # Final evaluation
    final_eval_max_workers: str = "auto",  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L74
    final_eval_few_shots: int = 5,  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L56
    final_eval_batch_size: str = "auto",  # https://github.com/instructlab/instructlab/blob/v0.21.2/tests/testdata/default_config.yaml#L52
    final_eval_merge_system_user_message: bool = False,  # https://github.com/instructlab/instructlab/blob/v0.21.2/src/instructlab/model/evaluate.py#L474
    # General Evaluation Inputs
    eval_gpu_identifier: str = "nvidia.com/gpu",
    eval_judge_secret: str = "judge-secret",
    # Other options
    k8s_storage_class_name: str = "standard",  # FIXME: https://github.com/kubeflow/pipelines/issues/11396, https://issues.redhat.com/browse/RHOAIRFE-470
    k8s_storage_size: str = "100Gi",
):
    """InstructLab pipeline

    Args:
        output_oci_model_uri: The URI path to the OCI registry where the output model is pushed to.
        output_oci_registry_secret: The secret key to use for OCI output registry.
        output_model_name:  Model Registration parameter. The name of the model used during model registration.
        output_model_version: Model Registration parameter. The version of the model used during model registration.
        output_model_registry_api_url: Model Registration parameter. The API URL of the model registry used during model registration.
        output_model_registry_name: Model Registration parameter. The name of the model registry used for model registration. If not specified, the name is parsed from output_model_registry_api_url.
        output_modelcar_base_image: The base image used for output model. The default value does not work in a disconnected environment.

        sdg_repo_url: SDG parameter. Points to a taxonomy git repository. E.g. "https://github.com/instructlab/taxonomy.git"
        sdg_repo_secret: SDG parameter. The name of the k8s secret holding access credentials to the sdg_repo_url.
        sdg_repo_branch: SDG parameter. Points to a branch within the taxonomy git repository. If set, has priority over sdg_repo_pr
        sdg_repo_pr: SDG parameter. Points to a pull request against the taxonomy git repository
        sdg_teacher_secret: SDG parameter. The name of the k8s secret key holding access credentials to the teacher server.
        sdg_base_model: SDG parameter. The LLM model used to generate the synthetic dataset. This can be a model from OCI such as "oci://registry.redhat.io/rhelai1/modelcar-granite-8b-code-instruct:latest" or "s3://<BUCKET>/<PATH_TO_MODEL>".
        sdg_scale_factor: SDG parameter. The total number of instructions to be generated.
        sdg_pipeline: SDG parameter. Data generation pipeline to use. Available: 'simple', 'full', or a valid path to a directory of pipeline workflow YAML files. Note that 'full' requires a larger teacher model, Mixtral-8x7b.
        sdg_max_batch_len: SDG parameter. Maximum tokens per gpu for each batch that will be handled in a single step.
        sdg_sample_size: SDG parameter. Represents the sdg skills recipe sampling size as percentage in decimal form.
        sdg_batch_size: SDG parameter. The number of completions per request to the teacher model. This can be increased to improve SDG performance based on the hardware of the teacher model or reduced if SDG fails due to connection errors with the teacher model.
        sdg_num_workers: SDG parameter. The number of concurrent workers sending completion requests to the teacher model. This can be increased to improve SDG performance based on the hardware of the teacher model or reduced if SDG fails due to connection errors with the teacher model. Batching is disabled when sdg_num_workers=1.

        train_tolerations: Training parameter. List of tolerations applied to training pods.
        train_node_selectors: Training parameter. A JSON containing node selectors applied to training pods.
        train_gpu_identifier: Training parameter. The GPU type used for training pods, e.g. nvidia.com/gpu
        train_gpu_per_worker: Training parameter. Number of GPUs per each node/worker to use for training.
        train_cpu_per_worker: Training parameter. Number of CPUs per each node/worker to use for training.
        train_memory_per_worker: Training parameter. Memory per GPU per each node/worker to use for training.
        train_num_workers: Training parameter. Number of nodes/workers to train on.
        train_num_epochs_phase_1: Training parameter for in Phase 1. Number of epochs to run training.
        train_num_epochs_phase_2: Training parameter for in Phase 2. Number of epochs to run training.
        train_effective_batch_size_phase_1: Training parameter for in Phase 1. The number of samples in a batch that the model should see before its parameters are updated.
        train_effective_batch_size_phase_2: Training parameter for in Phase 2. The number of samples in a batch that the model should see before its parameters are updated.
        train_learning_rate_phase_1: Training parameter for in Phase 1. How fast we optimize the weights during gradient descent. Higher values may lead to unstable learning performance. It's generally recommended to have a low learning rate with a high effective batch size.
        train_learning_rate_phase_2: Training parameter for in Phase 2. How fast we optimize the weights during gradient descent. Higher values may lead to unstable learning performance. It's generally recommended to have a low learning rate with a high effective batch size.
        train_num_warmup_steps_phase_1: Training parameter for in Phase 1. The number of steps a model should go through before reaching the full learning rate. We start at 0 and linearly climb up to train_learning_rate.
        train_num_warmup_steps_phase_2: Training parameter for in Phase 2. The number of steps a model should go through before reaching the full learning rate. We start at 0 and linearly climb up to train_learning_rate.
        train_save_samples: Training parameter. Number of samples the model should see before saving a checkpoint.
        train_max_batch_len: Training parameter. Maximum tokens per gpu for each batch that will be handled in a single step.
        train_seed: Training parameter. Random seed for initializing training.

        mt_bench_max_workers: MT Bench parameter. Number of workers to use for evaluation with mt_bench or mt_bench_branch. Must be a positive integer or 'auto'.
        mt_bench_merge_system_user_message: MT Bench parameter. Boolean indicating whether to merge system and user messages (required for Mistral based judges)

        final_eval_max_workers: Final model evaluation parameter for MT Bench Branch. Number of workers to use for evaluation with mt_bench or mt_bench_branch. Must be a positive integer or 'auto'.
        final_eval_few_shots: Final model evaluation parameter for MMLU. Number of question-answer pairs provided in the context preceding the question used for evaluation.
        final_eval_batch_size: Final model evaluation parameter for MMLU. Batch size for evaluation. Valid values are a positive integer or 'auto' to select the largest batch size that will fit in memory.
        final_eval_merge_system_user_message: Final model evaluation parameter for MT Bench Branch. Boolean indicating whether to merge system and user messages (required for Mistral based judges)

        eval_gpu_identifier: General evaluation parameter. The GPU type used for training pods, e.g. nvidia.com/gpu
        eval_judge_secret: General evaluation parameter: The name of the k8s secret key holding access credentials to the judge server.

        k8s_storage_class_name: A Kubernetes StorageClass name for persistent volumes. Selected StorageClass must support RWX PersistentVolumes.
        k8s_storage_size: The storage size of the persistent volume used for data passing within the pipeline.
    """
    # Pre-requisites check stage
    prerequisites_check_task = prerequisites_check_op(
        sdg_repo_url=sdg_repo_url,
        output_oci_registry_secret=output_oci_registry_secret,
        eval_judge_secret=eval_judge_secret,
        sdg_teacher_secret=sdg_teacher_secret,
        sdg_batch_size=sdg_batch_size,
        sdg_num_workers=sdg_num_workers,
        output_oci_model_uri=output_oci_model_uri,
        output_model_registry_api_url=output_model_registry_api_url,
        output_model_name=output_model_name,
        output_model_version=output_model_version,
    )

    # SDG stage
    sdg_input_pvc_task = CreatePVC(
        pvc_name_suffix="-sdg",
        access_modes=["ReadWriteMany"],
        size=k8s_storage_size,
        storage_class_name=k8s_storage_class_name,
    )
    sdg_input_pvc_task.after(prerequisites_check_task)

    model_tokenizer_source_task = dsl.importer(
        artifact_uri=f"oci://{RUNTIME_GENERIC_IMAGE}", artifact_class=dsl.Model
    )
    model_tokenizer_source_task.after(prerequisites_check_task)

    sdg_task = sdg_op(
        num_instructions_to_generate=sdg_scale_factor,
        pipeline=sdg_pipeline,
        repo_branch=sdg_repo_branch,
        repo_pr=sdg_repo_pr,
        sdg_sampling_size=sdg_sample_size,
        sdg_secret_name=sdg_teacher_secret,
        sdg_batch_size=sdg_batch_size,
        sdg_num_cpus=sdg_num_workers,
        repo_url=sdg_repo_url,
        taxonomy_repo_secret=sdg_repo_secret,
        tokenizer_model=model_tokenizer_source_task.output,
    )
    sdg_task.set_env_variable("HOME", "/tmp")
    sdg_task.set_env_variable("HF_HOME", "/tmp")

    mount_pvc(
        task=sdg_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/data",
    )
    sdg_task.set_caching_options(False)
    sdg_task.after(prerequisites_check_task)

    # Upload "sdg" and "taxonomy" artifacts to S3 without blocking the rest of the workflow
    taxonomy_to_artifact_task = taxonomy_to_artifact_op()
    taxonomy_to_artifact_task.after(sdg_task)
    mount_pvc(
        task=taxonomy_to_artifact_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/data",
    )
    sdg_to_artifact_task = sdg_to_artifact_op()
    sdg_to_artifact_task.after(sdg_task)
    mount_pvc(
        task=sdg_to_artifact_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/data",
    )

    # uncomment if updating image with same tag
    # set_image_pull_policy(sdg_task, "Always")

    # Training stage
    model_source_task = dsl.importer(
        artifact_uri=sdg_base_model, artifact_class=dsl.Model
    )
    model_source_task.after(prerequisites_check_task)

    model_pvc_task = CreatePVC(
        pvc_name_suffix="-model-cache",
        access_modes=["ReadWriteMany"],
        size=k8s_storage_size,
        storage_class_name=k8s_storage_class_name,
    )
    model_pvc_task.after(prerequisites_check_task)

    model_to_pvc_task = model_to_pvc_op(model=model_source_task.output)
    model_to_pvc_task.set_caching_options(False)
    mount_pvc(
        task=model_to_pvc_task, pvc_name=model_pvc_task.output, mount_path="/model"
    )

    # Data processing
    data_processing_task = data_processing_op(max_batch_len=sdg_max_batch_len)
    mount_pvc(
        task=data_processing_task,
        pvc_name=model_pvc_task.output,
        mount_path="/model",
    )
    mount_pvc(
        task=data_processing_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/data",
    )
    data_processing_task.after(model_to_pvc_task, sdg_task)
    data_processing_task.set_caching_options(False)
    data_processing_task.set_env_variable("XDG_CACHE_HOME", "/tmp")

    # Upload "skills_processed_data" and "knowledge_processed_data" artifacts to S3 without blocking the rest of the workflow
    skills_processed_data_to_artifact_task = skills_processed_data_to_artifact_op()
    skills_processed_data_to_artifact_task.after(data_processing_task)
    mount_pvc(
        task=skills_processed_data_to_artifact_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/data",
    )
    skills_processed_data_to_artifact_task.set_caching_options(False)
    knowledge_processed_data_to_artifact_task = (
        knowledge_processed_data_to_artifact_op()
    )
    knowledge_processed_data_to_artifact_task.after(data_processing_task)
    mount_pvc(
        task=knowledge_processed_data_to_artifact_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/data",
    )
    knowledge_processed_data_to_artifact_task.set_caching_options(False)

    output_pvc_task = CreatePVC(
        pvc_name_suffix="-output",
        access_modes=["ReadWriteMany"],
        size=k8s_storage_size,
        storage_class_name=k8s_storage_class_name,
    )
    output_pvc_task.after(prerequisites_check_task)

    # Training 1
    # Using pvc_create_task.output as PyTorchJob name since dsl.PIPELINE_* global variables do not template/work in KFP v2
    # https://github.com/kubeflow/pipelines/issues/10453
    training_phase_1 = pytorch_job_launcher_op(
        gpu_identifier=train_gpu_identifier,
        cpu_per_worker=train_cpu_per_worker,
        memory_per_worker=train_memory_per_worker,
        tolerations=train_tolerations,
        node_selectors=train_node_selectors,
        model_pvc_name=model_pvc_task.output,
        input_pvc_name=sdg_input_pvc_task.output,
        name_suffix=sdg_input_pvc_task.output,
        output_pvc_name=output_pvc_task.output,
        phase_num=1,
        base_image=RHELAI_IMAGE,
        nproc_per_node=train_gpu_per_worker,
        nnodes=train_num_workers,
        num_epochs=train_num_epochs_phase_1,
        effective_batch_size=train_effective_batch_size_phase_1,
        learning_rate=train_learning_rate_phase_1,
        num_warmup_steps=train_num_warmup_steps_phase_1,
        save_samples=train_save_samples,
        max_batch_len=train_max_batch_len,
        seed=train_seed,
    )
    training_phase_1.after(data_processing_task, model_to_pvc_task)
    training_phase_1.set_caching_options(False)

    #### Train 2
    training_phase_2 = pytorch_job_launcher_op(
        gpu_identifier=train_gpu_identifier,
        cpu_per_worker=train_cpu_per_worker,
        memory_per_worker=train_memory_per_worker,
        tolerations=train_tolerations,
        node_selectors=train_node_selectors,
        model_pvc_name=model_pvc_task.output,
        input_pvc_name=sdg_input_pvc_task.output,
        name_suffix=sdg_input_pvc_task.output,
        output_pvc_name=output_pvc_task.output,
        phase_num=2,
        base_image=RHELAI_IMAGE,
        nproc_per_node=train_gpu_per_worker,
        nnodes=train_num_workers,
        num_epochs=train_num_epochs_phase_2,
        effective_batch_size=train_effective_batch_size_phase_2,
        learning_rate=train_learning_rate_phase_2,
        num_warmup_steps=train_num_warmup_steps_phase_2,
        save_samples=train_save_samples,
        max_batch_len=train_max_batch_len,
        seed=train_seed,
    )

    training_phase_2.set_caching_options(False)
    training_phase_2.after(training_phase_1)

    mount_pvc(
        task=training_phase_2,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )

    # MT_Bench Evaluation of models

    run_mt_bench_task = run_mt_bench_op(
        models_folder="/output/phase_2/model/hf_format",
        max_workers=mt_bench_max_workers,
        merge_system_user_message=mt_bench_merge_system_user_message,
        judge_secret_name=eval_judge_secret,
    )
    mount_pvc(
        task=run_mt_bench_task,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )
    run_mt_bench_task.set_env_variable("HOME", "/tmp")
    run_mt_bench_task.set_env_variable("HF_HOME", "/tmp")
    run_mt_bench_task.set_accelerator_type(eval_gpu_identifier)
    run_mt_bench_task.set_accelerator_limit(1)
    run_mt_bench_task.set_caching_options(False)
    run_mt_bench_task.after(training_phase_2)

    # uncomment if updating image with same tag
    # set_image_pull_policy(run_mt_bench_task, "Always")

    final_eval_task = run_final_eval_op(
        candidate_model="/output/phase_2/model/hf_format/candidate_model",
        # TODO: DO we need both candidate_branch and base_branch
        base_branch=sdg_repo_branch,
        candidate_branch=sdg_repo_branch,
        base_model_dir="/model/",
        max_workers=final_eval_max_workers,
        merge_system_user_message=final_eval_merge_system_user_message,
        few_shots=final_eval_few_shots,
        batch_size=final_eval_batch_size,
        judge_secret_name=eval_judge_secret,
    )
    mount_pvc(
        task=final_eval_task, pvc_name=output_pvc_task.output, mount_path="/output"
    )
    mount_pvc(
        task=final_eval_task,
        pvc_name=sdg_input_pvc_task.output,
        mount_path="/input",
    )
    mount_pvc(
        task=final_eval_task,
        pvc_name=model_pvc_task.output,
        mount_path="/model",
    )

    final_eval_task.set_env_variable("HOME", "/tmp")
    final_eval_task.set_env_variable("HF_HOME", "/tmp")

    # uncomment if updating image with same tag
    # set_image_pull_policy(final_eval_task, "Always")

    final_eval_task.after(run_mt_bench_task)
    final_eval_task.set_accelerator_type(eval_gpu_identifier)
    final_eval_task.set_accelerator_limit(1)
    final_eval_task.set_caching_options(False)

    output_model_task = upload_model_op(
        output_oci_model_uri=output_oci_model_uri,
        output_oci_registry_secret=output_oci_registry_secret,
        output_modelcar_base_image=output_modelcar_base_image,
        run_id=dsl.PIPELINE_JOB_ID_PLACEHOLDER,
        run_name=dsl.PIPELINE_JOB_NAME_PLACEHOLDER,
        output_model_name=output_model_name,
        output_model_version=output_model_version,
        output_model_registry_name=output_model_registry_name,
        output_model_registry_api_url=output_model_registry_api_url,
        pvc_path="/output/phase_2/model/hf_format/candidate_model",
        oci_temp_dir="/output",
    )
    output_model_task.after(run_mt_bench_task)
    output_model_task.set_caching_options(False)
    mount_pvc(
        task=output_model_task,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )

    output_mt_bench_task = pvc_to_mt_bench_op(
        pvc_path="/output/mt_bench_data.json",
    )
    output_mt_bench_task.after(run_mt_bench_task)
    output_mt_bench_task.set_caching_options(False)

    mount_pvc(
        task=output_mt_bench_task,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )

    output_mt_bench_branch_task = pvc_to_mt_bench_branch_op(
        pvc_path="/output/mt_bench_branch/mt_bench_branch_data.json",
    )
    output_mt_bench_branch_task.after(final_eval_task)
    output_mt_bench_branch_task.set_caching_options(False)

    mount_pvc(
        task=output_mt_bench_branch_task,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )

    output_mmlu_branch_task = pvc_to_mmlu_branch_op(
        pvc_path="/output/mmlu_branch/mmlu_branch_data.json",
    )
    output_mmlu_branch_task.after(final_eval_task)
    output_mmlu_branch_task.set_caching_options(False)

    mount_pvc(
        task=output_mmlu_branch_task,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )

    sdg_pvc_delete_task = DeletePVC(pvc_name=sdg_input_pvc_task.output)
    sdg_pvc_delete_task.after(final_eval_task)

    model_pvc_delete_task = DeletePVC(pvc_name=model_pvc_task.output)
    model_pvc_delete_task.after(final_eval_task)

    generate_metrics_report_task = generate_metrics_report_op()
    generate_metrics_report_task.after(final_eval_task)
    generate_metrics_report_task.set_caching_options(False)
    mount_pvc(
        task=generate_metrics_report_task,
        pvc_name=output_pvc_task.output,
        mount_path="/output",
    )

    output_pvc_delete_task = DeletePVC(pvc_name=output_pvc_task.output)
    output_pvc_delete_task.after(
        output_model_task,
        output_mt_bench_task,
        output_mmlu_branch_task,
        output_mt_bench_branch_task,
        generate_metrics_report_task,
    )

    return


@dsl.pipeline(
    display_name="InstructLab - base model importer",
    name="instructlab-base-importer",
    description="Helper pipeline to the InstructLab pipeline which allows users to seed/import a new base model",
)
def import_base_model_pipeline(
    # hf_token_secret: str = "", # FIXME: Don't use hardcoded secret/configmap names once fixed upstream: https://github.com/kubeflow/pipelines/issues/11395
    # oci_pull_secret: str = "", # FIXME: Don't use hardcoded secret/configmap names once fixed upstream: https://github.com/kubeflow/pipelines/issues/11395
    repository: str = "docker://registry.redhat.io/rhelai1/granite-7b-starter",
    release: str = "latest",
):
    """InstructLab - base model importer.

    Args:
        repository: Hugging Face or OCI repository of the model to download. OCI repository must have a docker:// prefix
        release: The revision of the model to download - e.g. a branch, tag, or commit hash for Hugging Face repositories and tag or commit hash for OCI repositories.
        hf_token_secret: Name of existing Kubernetes secret which contains HF_TOKEN value for Hugging Face repositories. Mandatory for all repositories besides those which belong to the "instructlab" organization.
        oci_pull_secret: Name of existing Kubernetes secret of .dockerconfigjson type for OCI repository authentication.
    """
    importer_task = ilab_importer_op(repository=repository, release=release)

    # FIXME: Don't use hardcoded secret/configmap names once fixed upstream: https://github.com/kubeflow/pipelines/issues/11395
    # FIXME: Make env variables optional once implemented upstream: https://github.com/kubeflow/pipelines/issues/11401
    # This pipeline is currently unusable outside of ocp-beta-test.nerc.mghpcc.org cluster, `ilab` namespace due to the hardcoded names...
    use_secret_as_env(importer_task, "hugging-face-token", dict(HF_TOKEN="HF_TOKEN"))
    importer_task.set_env_variable(
        "REGISTRY_AUTH_FILE", "/mnt/containers/.dockerconfigjson"
    )
    use_secret_as_volume(
        importer_task, "7033380-ilab-pull-secret", mount_path="/mnt/containers"
    )
    importer_task.set_env_variable("XDG_CACHE_HOME", "/tmp")
    importer_task.set_env_variable("XDG_CONFIG_HOME", "/tmp")
    importer_task.set_env_variable("XDG_DATA_HOME", "/tmp")


@click.group(invoke_without_command=True)
@click.pass_context
def cli(ctx: click.Context):
    if ctx.invoked_subcommand is None:
        generate_pipeline()


def generate_pipeline():
    pipelines = [
        (ilab_pipeline, PIPELINE_FILE_NAME),
        (import_base_model_pipeline, IMPORTER_PIPELINE_FILE_NAME),
    ]

    with click.progressbar(
        pipelines,
        label="Generating pipeline",
        item_show_func=lambda p: p[1] if p is not None else "",
    ) as bar:
        for pipeline_func, pipeline_file in bar:
            compiler.Compiler().compile(pipeline_func, pipeline_file)


@cli.command(name="run")
@click.option("-e", "--experiment", help="Set KFP experiment name.")
@click.option("-r", "--run", "run_name", help="Set KFP run name.")
@click.option(
    "-p",
    "--param",
    help="Override default parameters in KEY=VALUE format. Default parameters are suitable for dev cluster - the MOC cluster, `ilab` namespace.",
    multiple=True,
)
def run(experiment, run_name, param):
    """
    Run the pipeline immediately against current kubernetes context (cluster and namespace).

    Command sets expected dev-cluster friendly default values when submitting.
    """
    from utils.kfp_client import get_kfp_client

    client = get_kfp_client()

    dev_arguments = {
        "k8s_storage_class_name": "nfs-csi",
        "sdg_base_model": "s3://ilab-pipeline-b1d4c2b1-ab00-4e7f-b985-697bda3df385/instructlab-base-importer/648f36d0-e3f0-43b8-8adb-530576beb675/ilab-importer-op/model/granite-7b-starter",
        "train_num_epochs_phase_1": 2,
        "train_num_epochs_phase_2": 2,
        "train_num_warmup_steps_phase_1": 100,
        "train_num_warmup_steps_phase_2": 100,
        "train_learning_rate_phase_1": 1e-4,
        "train_learning_rate_phase_2": 1e-4,
        "sdg_sample_size": 0.0002,
    }

    try:
        parsed_params = dict(item.split("=") for item in param)
    except ValueError as e:
        raise click.BadOptionUsage(
            "param", "Parameters are required to be passed in KEY=VALUE format"
        ) from e

    arguments = {**dev_arguments, **parsed_params}
    client.create_run_from_pipeline_func(
        pipeline_func=ilab_pipeline,
        experiment_name=experiment,
        run_name=run_name,
        arguments=arguments,
    )


if __name__ == "__main__":
    cli()
