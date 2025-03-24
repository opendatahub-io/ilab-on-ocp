# Kubernetes manifests

This folder contains supplementary Kubernetes deployment manifests for
the InstructLab pipeline.

#### Deploying Teacher and Judge Models:

In addition to model training, InstructLab also performs Synthetic Data Generation (SDG) and Model Evaluation. In both
cases another LLM is required to complete these steps. Since these models do not change frequently, we recommend serving
them independent of the specific InstructLab pipeline. This allows these models to be used as a shared resources
across the organization.

1. Deploy the Teacher Model following these [mixtral serving instructions].
2. Deploy the Judge Model following these [prometheus serving instructions].

Once these two model servers are deployed, we need to add the following secrets to our namespace so that the InstructLab
pipeline can successfully communicate with each model.

```yaml
# model_secrets.yaml
kind: Secret
apiVersion: v1
metadata:
  name: <teacher-server-secret-name>
stringData:
  api_token:
  endpoint:
  model_name:
type: Opaque
---
kind: Secret
apiVersion: v1
metadata:
  name: <judge-server-secret-name>
stringData:
  api_token:
  endpoint:
  model_name:
type: Opaque
```

Deploy these secrets to the Data Science project where the InstructLab pipeline
will be executed:

```bash
oc -n  <data-science-project-name/namespace> apply -f model_secrets.yaml
```

> [!Note]
> Be sure to add any required CAs to trust to the DSCI or DSPA.

[mixtral serving instructions]: /manifests/mixtral_serve/README.md
[prometheus serving instructions]: /manifests/prometheus_serve/README.md
