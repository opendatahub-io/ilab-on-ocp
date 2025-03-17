## Simple chatbot

This folder holds the resource definitions to launch a chatbot.
Before deploying, update the values in [configmap.yaml](./configmap.yaml) and [secret-token.yaml](./secret-token.yaml)
Specifically, `model_endpoint` value must be provided.
Optionally, `model_name` and `api_key` can be provided.

Update the deployment as necessary and
run this from the root of the repository


```bash
oc apply --kustomize ./kubernetes_yaml/chatbot
```

### Chatbot

The chatbot image is built from
[ai-lab-recipes repository chatbot](https://github.com/containers/ai-lab-recipes/blob/main/recipes/natural_language_processing/chatbot/app/Containerfile)
with the below system prompt line from
[chatbot_ui.py](https://github.com/containers/ai-lab-recipes/blob/main/recipes/natural_language_processing/chatbot/app/chatbot_ui.py)
commented out, since it's not compatible with vLLM:

```bash
prompt = ChatPromptTemplate.from_messages([
    #("system", "You are world class technical advisor."),
    MessagesPlaceholder(variable_name="history"),
    ("user", "{input}")
])
```


## Candidate model inference service

This folder also contains an example InferenceService definition. Modify [candidate-server.yaml](./candidate-server.yaml) as needed to launch a model
from `S3` with `vLLM`.
