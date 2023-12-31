import random

from src import SEED
from tqdm import tqdm
from copy import deepcopy
from typing import List, Dict, Tuple, Any, Generator
from datasets import load_dataset, DatasetDict
from dataclasses import dataclass
from abc import abstractmethod
import numpy as np


def load_data(data_name: str, lim: int = None) -> Tuple["train", "val", "test"]:
    data_ret = {
        "rt": _load_rotten_tomatoes,
        "gigaword": _load_gigaword,
    }
    return data_ret[data_name](lim)


class PromptLoader:
    """Class to load prompts from different datasets

    Each dataset is immediately loaded into cache
    """

    def __init__(self, incontext: str, eval: str):
        """Load all the datasets into memory"""

        if eval == "gigaword":
            self.eval_set = GigawordDataLoader()
        elif eval == "dailymail":
            self.eval_set = DailymailDataLoader()
        elif eval == "rotten_tomatoes":
            self.eval_set = RottenTomatoesDataLoader()

        if incontext == eval:
            # Prevent having to loading same dataset twice
            self.incontext_set = self.eval_set
        elif incontext == "gigaword":
            self.incontext_set = GigawordDataLoader()
        elif incontext == "dailymail":
            self.incontext_set = DailymailDataLoader()
        elif incontext == "wikicat":
            self.incontext_set = WikicatDataLoader()
        elif incontext == "rotten_tomatoes":
            self.incontext_set = RottenTomatoesDataLoader()
        elif incontext == "tweetqa":
            self.incontext_set = TweetQADataLoader()

    def load_prompt(self, num_examples: int):
        """Return prompts from different datasets
        prompt = incontext + eval

        The prompts are pre-loaded into memory.
        This is because not much RAM is required,
        and the pre-processing is slow.

        % TODO: add functionality to limit the test size(deterministically)

        % TODO: if this is implemened as a dataset transform,
        then this can be cached (tho this will only save around 40s)

        Args:
            incontext: name of the dataset to load incontext prompts from
            eval: name of the dataset to load evaluation prompts from
            num_examples: number of incontext examples to include
        """

        prompts = [
            (self.incontext_set.incontext_prompt(num_examples, seed=idx) + eval_prompt)
            for idx, eval_prompt in enumerate(self.eval_set.eval_prompt())
        ]

        return prompts

    def load_prompt_iterative(self, num_examples: int):
        """Return prompts from different datasets - iterative version of prompts: returns list of lists of dictionary
        first list iterates through samples in test dataset
        second list iterates through the user/assistant messages in turn
        the dictionary has keys
             'role': which is either 'user' or 'assistant;
             'content': the message in that turn

        e.g. the list of message for a single sample with a single incontent example will be
                [
            {'role': 'user',
            'content': 'you are a summary system'.\n What is the summary of (1)
            },

            {'role': 'assistannt',
            'content' : summary of (1)
            }

                {'role': user,
                'content': What is the summary of eval_sample
            }
                ]
        """

        # prompts = [
        #     (self.incontext_set.incontext_prompt(num_examples, seed=idx) + eval_prompt)
        #     for idx, eval_prompt in enumerate(self.eval_set.eval_prompt())
        # ]

        prompts = [self.incontext_set.incontext_prompt_iterative(num_examples, seed=idx) + [{'role':'user', 'content':eval_prompt}]
                    for idx, eval_prompt in enumerate(self.eval_set.eval_prompt())]

        return prompts

    def load_testdata(self) -> list[str]:
        """Return the test data reference as a list[str]

        This is used for evaluation
        """
        return self.eval_set.load_test_reference()


@dataclass
class DataLoader:
    """Abstract class for loading data"""

    dataset_name: str
    _dataset: DatasetDict | None = None

    @property
    def dataset(self):
        if self._dataset is None:
            if self.dataset_name == "cnn_dailymail":
                self._dataset = load_dataset(self.dataset_name, "3.0.0")
            else:
                self._dataset = load_dataset(self.dataset_name)
        return self._dataset

    @abstractmethod
    def incontext_prompt(self, num_examples: int, seed: int = SEED):
        ...

    @abstractmethod
    def eval_prompt(self):
        ...


@dataclass
class RottenTomatoesDataLoader(DataLoader):
    """Dataloader for rotten tomatoes dataset

    NOTE: DatasetDict is of the form:
    {train, validation, test} with features: {text, label}

    The `labels` are mapped to `sentiments`
    1 -> positive; 0 -> negative
    """

    PROMPT_PREFIX = "Please read the following pairs of movie reviews and sentiment:\n"

    def __init__(self):
        super().__init__(dataset_name="rotten_tomatoes")

        # Map all labels to sentiments
        self._dataset = self.dataset.map(RottenTomatoesDataLoader._label_to_sentiment)

        # Map the training set to incontext prompts
        self.train = self.dataset["train"]
        self.train = self.train.map(RottenTomatoesDataLoader._prompt)

        # Map the test set to evaluation prompts
        self.test = self.dataset["test"]
        self.test = self.test.map(RottenTomatoesDataLoader._eval_prompt)

    def load_test_reference(self):
        """Return the test data as a list[str]"""
        return self.test["sentiment"]

    @staticmethod
    def _label_to_sentiment(example: dict[str, Any]) -> dict[str, str]:
        """Map the label to sentiment"""
        return {
            "sentiment": "positive" if example["label"] == 1 else "negative",
        }

    @staticmethod
    def _prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to incontext prompt"""
        return {
            "prompt": (
                "review: " + example["text"] + "\nsentiment: " + example["sentiment"]
            ),
        }

    @staticmethod
    def _eval_prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to evaluation prompt"""
        return {
            "eval_prompt": "Please perform a Sentiment Classification task. "
            "Given the following movie review, assign a sentiment label from ['negative', 'positive']. "
            "Return only the sentiment label without any other text.\n"
            + example["text"]
        }

    def incontext_prompt(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return ""
        out = RottenTomatoesDataLoader.PROMPT_PREFIX
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        out = out + "\n".join(examples) + "\n"
        return out

    def incontext_prompt_iterative(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return []
        out = []
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        for ex in examples:
            command =  "Please perform a Sentiment Classification task. "
            "Given the following movie review, assign a sentiment label from ['negative', 'positive']. "
            "Return only the sentiment label without any other text.\n"
            parts = ex.split("\nsentiment: ")
            out.append({'role':'user', 'content':command+parts[0]})
            out.append({'role':'assistant', 'content':parts[1]})
        return out

    def eval_prompt(self) -> Generator[str, None, None]:
        """Yields prompt for evaluation examples"""

        for eval_prompt in self.test["eval_prompt"]:
            yield eval_prompt


class GigawordDataLoader(DataLoader):
    """DataLoader for gigaword dataset

    NOTE: DatasetDict is of the form:
    {train, validation, test} with features: {document, summary}
    """

    PROMPT_PREFIX = "Please read the following pairs of texts and summaries:\n"

    def __init__(self):
        super().__init__(dataset_name="gigaword")

        # Map the training set to incontext prompts
        self.train = self.dataset["train"]
        self.train = self.train.map(GigawordDataLoader._prompt)

        # Map the test set to evaluation prompts
        self.test = self.dataset["test"]
        self.test = self.test.map(GigawordDataLoader._eval_prompt)

    def load_test_reference(self):
        """Return the test data as a list[str]"""
        return self.test["summary"]

    @staticmethod
    def _prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to incontext prompt"""
        return {
            "prompt": (
                "article: " + example["document"] + "\nsummary: " + example["summary"]
            ),
        }

    @staticmethod
    def _eval_prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to evaluation prompt"""
        return {
            "eval_prompt": "Please summarize the following article.\n"
            + example["document"],
        }

    def incontext_prompt(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return ""
        out = GigawordDataLoader.PROMPT_PREFIX
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)

        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        # examples = self.train.shuffle(seed=seed, keep_in_memory=True).select(
        #     range(num_examples), keep_in_memory=True
        # )["prompt"]
        out = out + "\n".join(examples) + "\n"
        return out

    def incontext_prompt_iterative(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return []
        # out = GigawordDataLoader.PROMPT_PREFIX
        out = []
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        # examples = self.train.shuffle(seed=seed, keep_in_memory=True).select(
        #     range(num_examples), keep_in_memory=True
        # )["prompt"]

        # out = out + "\n".join(examples) + "\n"
        for ex in examples:
            command = "Please summarize the following article.\n"
            parts = ex.split("\nsummary: ")
            out.append({'role':'user', 'content':command+parts[0]})
            out.append({'role':'assistant', 'content':parts[1]})
        return out

    def eval_prompt(self) -> Generator[str, None, None]:
        """Yields prompt for evaluation examples"""

        for eval_prompt in self.test["eval_prompt"]:
            yield eval_prompt


class DailymailDataLoader(DataLoader):
    """DataLoader for dailymail dataset

    NOTE: DatasetDict is of the form:
    {train, validation, test} with features: {'article', 'highlights', 'id'}
    """

    PROMPT_PREFIX = "Please read the following pairs of texts and summaries:\n"

    def __init__(self):
        super().__init__(dataset_name="cnn_dailymail")

        # Map the training set to incontext prompts
        self.train = self.dataset["train"]
        self.train = self.train.map(DailymailDataLoader._prompt)

        # Map the test set to evaluation prompts
        self.test = self.dataset["test"]
        self.test = self.test.map(DailymailDataLoader._eval_prompt)

    def load_test_reference(self):
        """Return the test data reference (answers) as a list[str]"""
        return self.test["highlights"]

    @staticmethod
    def _prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to incontext prompt"""
        return {
            "prompt": (
                "article: " + example["article"] + "\nsummary: " + example["highlights"]
            ),
        }

    @staticmethod
    def _eval_prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to evaluation prompt"""
        return {
            "eval_prompt": "Please summarize the following article.\n"
            + example["article"],
        }

    def incontext_prompt(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return ""
        out = DailymailDataLoader.PROMPT_PREFIX
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        out = out + "\n".join(examples) + "\n"
        return out
    
    def incontext_prompt_iterative(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return []
        out = []
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        for ex in examples:
            command = "Please summarize the following article.\n"
            parts = ex.split("\nsummary: ")
            out.append({'role':'user', 'content':command+parts[0]})
            out.append({'role':'assistant', 'content':parts[1]})
        return out

    def eval_prompt(self) -> Generator[str, None, None]:
        """Yields prompt for evaluation examples"""

        for eval_prompt in self.test["eval_prompt"]:
            yield eval_prompt

    def eval_prompt(self) -> Generator[str, None, None]:
        """Yields prompt for evaluation examples"""

        for eval_prompt in self.test["eval_prompt"]:
            yield eval_prompt


def _load_rotten_tomatoes(lim: int = None):
    dataset = load_dataset("rotten_tomatoes")
    train = list(dataset["train"])[:lim]
    val = list(dataset["validation"])[:lim]
    test = list(dataset["test"])[:lim]

    # Modify the keys based on the template tags (see the paper)
    train = [change_key(t, "text", "Review") for t in train]
    val = [change_key(t, "text", "Review") for t in val]
    test = [change_key(t, "text", "Review") for t in test]

    train = [change_key(t, "label", "Sentiment") for t in train]
    val = [change_key(t, "label", "Sentiment") for t in val]
    test = [change_key(t, "label", "Sentiment") for t in test]

    mapping = {0: "negative", 1: "positive"}
    train = [content_map(t, "Sentiment", mapping) for t in train]
    val = [content_map(t, "Sentiment", mapping) for t in val]
    test = [content_map(t, "Sentiment", mapping) for t in test]
    return train, val, test


class WikicatDataLoader(DataLoader):
    """DataLoader for wikicat dataset

    NOTE: DatasetDict is of the form:
    {train, validation, test} with features: {document, summary}
    """

    PROMPT_PREFIX = "Please read the following pairs of texts and summaries:\n"

    def __init__(self):
        super().__init__(dataset_name="GEM/wiki_cat_sum")

        # Map the training set to incontext prompts
        self.train = self.dataset["train"]
        self.train = self.train.map(WikicatDataLoader._prompt)

        # Map the test set to evaluation prompts
        self.test = self.dataset["test"]
        self.test = self.test.map(WikicatDataLoader._eval_prompt)

    def load_test_reference(self):
        """Return the test data as a list[str]"""
        return self.test["summary"]

    @staticmethod
    def _prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to incontext prompt"""
        return {
            "prompt": (
                "article: " + " ".join(example["paragraphs"]) + "\nsummary: " + " ".join(example["summary"]["text"])
            ),
        }

    @staticmethod
    def _eval_prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to evaluation prompt"""
        return {
            "eval_prompt": "Please summarize the following article.\n"
            + " ".join(example["paragraphs"]),
        }

    def incontext_prompt(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return ""
        out = WikicatDataLoader.PROMPT_PREFIX
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)

        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        # examples = self.train.shuffle(seed=seed, keep_in_memory=True).select(
        #     range(num_examples), keep_in_memory=True
        # )["prompt"]
        out = out + "\n".join(examples) + "\n"
        return out

    def incontext_prompt_iterative(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return []
        
        out = []
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        # examples = self.train.shuffle(seed=seed, keep_in_memory=True).select(
        #     range(num_examples), keep_in_memory=True
        # )["prompt"]

        # out = out + "\n".join(examples) + "\n"
        for ex in examples:
            command = "Please summarize the following article.\n"
            parts = ex.split("\nsummary: ")
            out.append({'role':'user', 'content':command+parts[0]})
            out.append({'role':'assistant', 'content':parts[1]})
        return out

    def eval_prompt(self) -> Generator[str, None, None]:
        """Yields prompt for evaluation examples"""

        for eval_prompt in self.test["eval_prompt"]:
            yield eval_prompt


class TweetQADataLoader(DataLoader):
    """DataLoader for TweetQA dataset
    """

    PROMPT_PREFIX = "Please read the following triplet of contexts, questions and answers and summaries:\n"

    def __init__(self):
        super().__init__(dataset_name="tweet_qa")

        # Map the training set to incontext prompts
        self.train = self.dataset["train"]
        self.train = self.train.map(TweetQADataLoader._prompt)

        # Map the test set to evaluation prompts
        self.test = self.dataset["test"]
        self.test = self.test.map(TweetQADataLoader._eval_prompt)

    def load_test_reference(self):
        """Return the test data as a list[str]"""
        return self.test["summary"]

    @staticmethod
    def _prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to incontext prompt"""
        return {
            "prompt": (
                "tweet: "+ example["Tweet"] + "\nquestion: " + example["Question"] + "\nanswer: " + example["Answer"][0]
            ),
        }

    @staticmethod
    def _eval_prompt(example: dict[str, Any]) -> dict[str, str]:
        """Transform a single example to evaluation prompt"""
        return {
            "eval_prompt": "Read the given tweet and answer the corresponding question.\n"
            "tweet: "+ example['Tweet']+"\nquestion: " + example["Question"]
        }

    def incontext_prompt(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return ""
        out = TweetQADataLoader.PROMPT_PREFIX
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)

        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        # examples = self.train.shuffle(seed=seed, keep_in_memory=True).select(
        #     range(num_examples), keep_in_memory=True
        # )["prompt"]
        out = out + "\n".join(examples) + "\n"
        return out

    def incontext_prompt_iterative(self, num_examples: int, seed: int = SEED):
        """Returns prompt for incontext examples

        Args:
            num_examples: number of incontext examples to include
            seed: random seed for selecting examples. e.g. this could be the iteration number
        """
        if num_examples == 0:
            return []
        
        out = []
        rng = np.random.default_rng(seed)
        idxs = rng.choice(len(self.train), num_examples, replace=False)
        examples = self.train.select(idxs, keep_in_memory=True)["prompt"]

        # examples = self.train.shuffle(seed=seed, keep_in_memory=True).select(
        #     range(num_examples), keep_in_memory=True
        # )["prompt"]

        # out = out + "\n".join(examples) + "\n"
        for ex in examples:
            command = "Read the given tweet and answer the corresponding question.\n"
            parts = ex.split("\nanswer: ")
            out.append({'role':'user', 'content':command+parts[0]})
            out.append({'role':'assistant', 'content':parts[1]})
        return out

    def eval_prompt(self) -> Generator[str, None, None]:
        """Yields prompt for evaluation examples"""

        for eval_prompt in self.test["eval_prompt"]:
            yield eval_prompt





def _create_splits(examples: list, ratio=0.8) -> Tuple[list, list]:
    examples = deepcopy(examples)
    split_len = int(ratio * len(examples))

    random.seed(1)
    random.shuffle(examples)

    split_1 = examples[:split_len]
    split_2 = examples[split_len:]
    return split_1, split_2


def change_key(ex: dict, old_key="content", new_key="text"):
    """convert key name from the old_key to 'text'"""
    ex = ex.copy()
    ex[new_key] = ex.pop(old_key)
    return ex


def content_map(ex: dict, target_key, mapping):
    ex[target_key] = mapping[ex[target_key]]
    return ex


def _multi_key_to_text(ex: dict, key1: str, key2: str):
    """concatenate contents of key1 and key2 and map to name text"""
    ex = ex.copy()
    ex["text"] = ex.pop(key1) + " " + ex.pop(key2)
    return ex


def _invert_labels(ex: dict):
    ex = ex.copy()
    ex["label"] = 1 - ex["label"]
    return ex


def _map_labels(ex: dict, map_dict={-1: 0, 1: 1}):
    ex = ex.copy()
    ex["label"] = map_dict[ex["label"]]
    return ex


def _rand_sample(lst, frac):
    random.Random(4).shuffle(lst)
    return lst[: int(len(lst) * frac)]
