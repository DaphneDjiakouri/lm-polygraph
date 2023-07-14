import torch
import numpy as np

from typing import Dict, List

from stat_calculators.stat_calculator import StatCalculator
from utils.model import Model


def get_embeddings_from_output(
    output,
    batch,
    hidden_state: List[str] = ["encoder", "decoder"],
    ignore_padding: bool = True,
    use_averaging: bool = True,
    all_layers: bool = False,
    aggregation_method: str = "mean",
):
    batch_embeddings = None
    batch_embeddings_decoder = None
    batch_size = len(batch["input_ids"])

    if use_averaging:
        if "decoder" in hidden_state:
            try:
                decoder_hidden_states = torch.stack(
                    [
                        torch.stack(hidden)
                        for hidden in output.decoder_hidden_states
                    ]
                )
                if all_layers:
                    agg_decoder_hidden_states = decoder_hidden_states[:, :, :, 0].mean(axis=1)
                else:
                    agg_decoder_hidden_states = decoder_hidden_states[:, -1, :, 0]

                batch_embeddings_decoder = aggregate(agg_decoder_hidden_states, aggregation_method, axis=0)
                batch_embeddings_decoder = batch_embeddings_decoder.reshape(batch_size, -1, agg_decoder_hidden_states.shape[-1])[:, 0]
            except:
                if all_layers:
                    agg_decoder_hidden_states = torch.stack(output.decoder_hidden_states).mean(axis=0)
                else:
                    agg_decoder_hidden_states = torch.stack(output.decoder_hidden_states)[-1]

                batch_embeddings_decoder = aggregate(agg_decoder_hidden_states, aggregation_method, axis=1)
                batch_embeddings_decoder = batch_embeddings_decoder.cpu().detach().reshape(-1, agg_decoder_hidden_states.shape[-1])

        if "encoder" in hidden_state:
            mask = batch["attention_mask"][:, :, None]
            seq_lens = batch["attention_mask"].sum(-1)[:, None]
            if all_layers:
                encoder_embeddings = aggregate(torch.stack(output.encoder_hidden_states), "mean", axis=0) * mask
            else:
                encoder_embeddings = output.encoder_hidden_states[-1] * mask

            if ignore_padding:
                if aggregation_method == "mean":
                    batch_embeddings = (
                        encoder_embeddings
                    ).sum(1) / seq_lens
                else:
                    batch_embeddings = aggregate(encoder_embeddings, aggregation_method, axis=1)
            else:
                batch_embeddings = aggregate(encoder_embeddings, aggregation_method, axis=1)
        if not ("encoder" in hidden_state) and not ("decoder" in hidden_state):
            raise NotImplementedError
    else:
        if "decoder" in hidden_state:
            decoder_hidden_states = torch.stack(
                [
                    torch.stack(hidden)
                    for hidden in output.decoder_hidden_states
                ]
            )
            last_decoder_hidden_states = decoder_hidden_states[-1, -1, :, 0]
            batch_embeddings_decoder = last_decoder_hidden_states.reshape(batch_size, -1, last_decoder_hidden_states.shape[-1])[:, 0]
        if "encoder" in hidden_state:
            batch_embeddings = predictions.encoder_hidden_states[-1][:, 0] 
        if not ("encoder" in hidden_state) and not ("decoder" in hidden_state):
            raise NotImplementedError

    return batch_embeddings, batch_embeddings_decoder


def aggregate(x, aggregation_method, axis):
    if aggregation_method == "max":
        return x.max(axis=axis).values
    elif aggregation_method == "mean":
        return x.mean(axis=axis)
    elif aggregation_method == "sum":
        return x.sum(axis=axis)

class EmbeddingsCalculator(StatCalculator):
    def __init__(self):
        super().__init__(['embeddings'], [])
        self.hidden_layer = -1

    def __call__(self, dependencies: Dict[str, np.array], texts: List[str], model: Model) -> Dict[str, np.ndarray]:
        batch: Dict[str, torch.Tensor] = model.tokenize(texts)
        batch = {k: v.to(model.device()) for k, v in batch.items()}
        with torch.no_grad():
            out = model.model.generate(
                **batch,
                output_scores=True,
                return_dict_in_generate=True,
                max_length=256,
                min_length=2,
                output_attentions=True,
                output_hidden_states=True,
                num_beams=1,
            )
        if model.model_type == "CausalLM":
            input_tokens_hs = out.hidden_states[0][self.hidden_layer]
            generated_tokens_hs = torch.cat([h[self.hidden_layer] for h in out.hidden_states[1:]], dim=1)
            embeddings = torch.cat([input_tokens_hs, generated_tokens_hs], dim=1).mean(axis=1)
            return {
                'embeddings_decoder': embeddings,
            }
        elif model.model_type == "Seq2SeqLM":
            embeddings_encoder, embeddings = get_embeddings_from_output(out, batch)
            return {
                'embeddings_encoder': embeddings_encoder,
                'embeddings_decoder': embeddings,
            }
        else:
            raise NotImplementedError
                
        