"""
*** This script calls OpenAI APIs that will charge you per use

OPENAI_API_KEY env variable should be set to run this script
"""
import csv
import json
import logging
import os
from pathlib import Path
from typing import List, Mapping, Optional, Sequence, Set, Tuple, Union

import numpy as np
from tqdm import tqdm

from .data_utils import read_questions, read_predict_file, read_annotations, Question, SimpleTokenizer
from .llm import OpenAIProxy
from .vicuna_llm import infer_vicuna
from .squad_evaluate import metric_max_over_ground_truths, regex_match, exact_match_score, f1_score

logger = logging.getLogger("eval")


def gpt_eval(question: Question, candidate_answer: str, openai_proxy: OpenAIProxy) -> Tuple[int, str]:
    answers = " or ".join(question.answers)
    q = question.text

    if not q.endswith("?"):
        q += "?"

    prompt = f"Question: {q}\nAnswer: {answers}\nCandidate: {candidate_answer}\n\nIs candidate correct?"
    response = openai_proxy(prompt)
    if response.lower().startswith("yes"):
        acceptable = "Yes"
    elif response.lower().startswith("no"):
        acceptable = "No"
    else:
        acceptable = ""
        logger.warning(f"Invalid response to `{q}` & `{candidate_answer}`: {response}")
        logger.warning(f"Prompt: {prompt}")

    return int(acceptable == "Yes"), response

def vicuna_eval(question: Question, candidate_answer: str) -> Tuple[int, str]:
    answers = " or ".join(question.answers)
    q = question.text

    with open('../passage_dpr.json', 'r') as json_file:
        context_passage = json.load(json_file)

    passage = context_passage.get(q, {}).get('contents')

    if not q.endswith("?"):
        q += "?"

    prompt = f"""
           You are an expert judge of a content. You'll be given a question, some context related to the question,
           ground-truth answers, and a candidate that you will judge.

           Using your internal knowledge and simple common sense reasoning, and given the provided context and ground-truth
           answers, try to verify if the candidate is correct or not.
           You are given an answer key/s but the contestant may provide an answer that isn't an exact match.
           Your job is to determine if the candidate is correct or not.

           Provide explanation for the comparison and give out answer based on the explanation as "yes" or "no".
           Here, "yes" represents that the candidate answer is relevant and correct based on either inbuilt knowledge,
           given context data or given ground-truth answers. If not, the answer based on the explanation would be "no".

           Here are some of the sample examples:

           Comprehend following context: "Pi Day"
           on the words ""pi"" and ""pie"" being homophones in English (), and the coincidental circular nature of a pie. Massachusetts Institute of Technology has often mailed its application decision letters to prospective students for delivery on Pi Day. Starting in 2012, MIT has announced it will post those decisions (privately) online on Pi Day at exactly 6:28 pm, which they have called ""Tau Time"", to honor the rival numbers pi and tau equally. In 2015, the regular decisions were put online at 9:26 AM, following that year's ""pi minute"". June 28 is ""Two Pi Day"", also known as ""Tau Day"". "Pi Alpha Phi"
           Pi Alpha Phi Pi Alpha Phi Fraternity, Inc. (ΠΑΦ, also Pi Alpha Phi or PAPhi) is an American university-level fraternity. It was founded in 1929 at the University of California, Berkeley and is the oldest active Asian-American Interest Fraternity in the nation. As of 2016, the fraternity has 16 active chapters, 6 colonies nationwide. Pi Alpha Phi Fraternity is a member the National APIA Panhellenic Association. In 1928, three enterprising members of the Class of 1930 conceived the idea to form a fraternity to serve the several hundred students of Chinese descent at the University of California, Berkeley. Wing C. "Pi Day"
           Pi Day Pi Day is an annual celebration of the mathematical constant (pi). Pi Day is observed on March 14 (3/14 in the ""month/day"" format) since 3, 1, and 4 are the first three significant digits of . In 2009, the United States House of Representatives supported the designation of Pi Day. Pi Approximation Day is observed on July 22 (22/7 in the ""day/month"" format), since the fraction is a common approximation of, which is accurate to two decimal places and dates from Archimedes. Two Pi Day, also known as Tau Day, is lightly observed on June 28 (6/28 in Pi
           in one turn, or as the ratio of a circle's circumference to its radius rather than its diameter, is more natural than and simplifies many formulas. Celebrations of this number, because it approximately equals 6.28, by making 28 June ""Tau Day"" and eating ""twice the pie"", have been reported in the media. However, this use of has not made its way into mainstream mathematics. In 1897, an amateur American mathematician attempted to persuade the Indiana legislature to pass the Indiana Pi Bill, which described a method to square the circle and contained text that implied various incorrect values for , "Pi Day"
           the ""month/day"" format). In 1988, the earliest known official or large-scale celebration of Pi Day was organized by Larry Shaw at the San Francisco Exploratorium, where Shaw worked as a physicist, with staff and public marching around one of its circular spaces, then consuming fruit pies. The Exploratorium continues to hold Pi Day celebrations. On March 12, 2009, the U.S. House of Representatives passed a non-binding resolution (), recognizing March 14, 2009 as National Pi Day. For Pi Day 2010, Google presented a Google Doodle celebrating the holiday, with the word Google laid over images of circles and pi symbols; "Alpha Pi Omega"
           Alpha Pi Omega Alpha Pi Omega Sorority, Inc. (ΑΠΩ) is the oldest historically American Indian sorority. It is also the largest Native American Greek letter organization, with 21 chapters across seven states and the District of Columbia. Alpha Pi Omega Sorority was founded on Sept. 1, 1994 at the University of North Carolina-Chapel Hill by four Native women. The founders, now known to the membership as the Four Winds, are Shannon Brayboy, Jamie Goins, Amy Locklear and Christie Strickland. With more than 100 tribes represented, the sorority has more than 800 sisters nationwide. Founding principles The sorority's founding principles are "Phi Epsilon Pi"
           Phi Epsilon Pi The Phi Epsilon Pi (ΦΕΠ) fraternity, active between 1904 and 1970 with a predominantly Jewish membership, was founded in New York City and eventually opened at least 48 chapters on college campuses across the United States and one in Canada. The Phi Epsilon Pi (PEP) fraternity was established on November 23, 1904 at the College of the City of New York (CCNY). Phi Epsilon Pi was incorporated in New York State on February 9, 1914 and became a member of the National Interfraternity Conference in 1921. The fraternity was founded on non-sectarian principles, but throughout the organization’s "Pi Day"
           and for the 30th anniversary in 2018, it was a Dominique Ansel pie with the circumference divided by its diameter. The entire month of March 2014 (3/14) was observed by some as ""Pi Month"". In the year 2015, March 14 was celebrated as ""Super Pi Day"". It had special significance, as the date is written as 3/14/15 in month/day/year format. At 9:26:53, the date and time together represented the first 10 digits of . Pi Day has been observed in many ways, including eating pie, throwing pies and discussing the significance of the number , due to a pun based "Pi Mu Epsilon"
           Pi Mu Epsilon Pi Mu Epsilon ( or PME) is the U.S. honorary national mathematics society. The society was founded at Syracuse University on May 25, 1914, by Professor Edward Drake Roe, Jr, and currently has chapters at 337 institutions across the US. Pi Mu Epsilon is dedicated to the promotion of mathematics and recognition of students who successfully pursue mathematical understanding. To promote mathematics, the National Pi Mu Epsilon Council co-sponsors an annual conference in conjunction with the Mathematical Association of America. The society also publishes a semi-annual journal, the Pi Mu Epsilon Journal, which both presents research papers Pi
           technologically minded groups. Several college cheers at the Massachusetts Institute of Technology include ""3.14159"". Pi Day in 2015 was particularly significant because the date and time 3/14/15 9:26:53 reflected many more digits of pi. During the 2011 auction for Nortel's portfolio of valuable technology patents, Google made a series of unusually specific bids based on mathematical and scientific constants, including . In 1958 Albert Eagle proposed replacing by (tau), where , to simplify formulas. However, no other authors are known to use in this way. Some people use a different value, , arguing that , as the number of radians

           Question: how long have we been celebrating pi day
           Ground-Truth Answers: "1988", "2009"
           Candidate: We have been celebrating pi day since 1988.

           Is the candidate correct?
           Since 1998 we have been celebrating pi day. Answer based on explanation: yes.

           ###

           Comprehend following context: "Daddy's Home 2"
           10, 2017. Although the film received generally negative reviews from critics, it grossed over $180 million worldwide on a $70 million budget. After finally becoming friends at the end of the first film, Brad Whittaker (Will Ferrell) and Dusty Mayron (Mark Wahlberg) have a co-dad system where their two children, Megan (Scarlett Estevez) and Dylan (Owen Vaccaro), take turns at each father's house. Dusty has also remarried, this time to Karen (Alessandra Ambrosio), a writer, and is stepdad to Adrianna (Didi Costine), Karen's daughter. Brad and his wife, Sara (Linda Cardellini), along with Dusty and Karen, attend a school play "Daddy's Home 2"
           Dusty and Brad discover that Brad's new stepdad is Chesley ""Sully"" Sullenberger, the pilot of the ""Miracle on the Hudson"" flight. Brad and Dusty remember that they watched the film ""Sully"" together not too long ago, and Brad appears to be welcoming towards him. Brad runs down the terminal and says that Sully will never replace his father, because Sully has only one great personal story, whereas his father has a million stories. In April 2016, the sequel was announced, with Will Ferrell and Mark Wahlberg reprising their roles, Sean Anders and John Morris writing the script, and Anders directing. "Daddy's Home 2"
           mistakes Brad for a chauffeur. When Dusty explains that Brad is the stepdad to his children, Kurt doesn't like it. Brad's overbearing and over-cheerful dad, Don (John Lithgow), arrives next, unnerving Kurt. Don tells Brad that his mother didn't come along, because she is taking care of Brad's uncle who isn't feeling well. Back at the house, Megan and Dylan warmly embrace Don, since he is very present in their lives, while Kurt hasn't seen the children since they were toddlers. Through jealousy of the affection the children show to Don, Kurt rents a large cabin through Airbnb, to house "Daddy's Home 2"
           Daddy's Home 2 Daddy's Home 2 is a 2017 American Christmas comedy film directed by Sean Anders and written by Anders and John Morris. A sequel to ""Daddy's Home"" (2015), it stars Will Ferrell, Mark Wahlberg, Linda Cardellini, John Cena, with John Lithgow and Mel Gibson. The plot follows now reformed-fathers Brad and Dusty (Ferrell and Wahlberg), now co-parenting Dusty's kids, who have to deal with their own fathers (Lithgow and Gibson) visiting for the holidays. Principal photography on the film began in Massachusetts in March 2017 and it was released in the United States by Paramount Pictures on November "Daddy's Home 2"
           Wahlberg mentioned that they would like to get Liam Neeson for the third installment of the film series. Daddy's Home 2 Daddy's Home 2 is a 2017 American Christmas comedy film directed by Sean Anders and written by Anders and John Morris. A sequel to ""Daddy's Home"" (2015), it stars Will Ferrell, Mark Wahlberg, Linda Cardellini, John Cena, with John Lithgow and Mel Gibson. The plot follows now reformed-fathers Brad and Dusty (Ferrell and Wahlberg), now co-parenting Dusty's kids, who have to deal with their own fathers (Lithgow and Gibson) visiting for the holidays. Principal photography on the film began "Daddy's Home 2"
           for Megan, where she announces to the whole audience that she doesn't like the fact that she has to go back and forth to different houses all the time. Back at the house, after the play, Brad and Dusty decide to do away with having two separate Christmases and instead do one ""together Christmas"". Dusty, however, finds out his tough fighter pilot/astronaut father Kurt (Mel Gibson) is coming for Christmas. At the airport the next day, Dusty tells Brad that his father is going to make fun of them since he won't understand their co-dad arrangement. When Kurt arrives, he "Daddy's Home 2"
           In January 2017, it was reported that Mel Gibson and John Lithgow were being sought to play the main characters' fathers in the film. The two were later confirmed to star, along with Linda Cardellini, John Cena, Owen Vaccaro and Scarlett Estevez, reprising their roles. Principal photography began on March 20, 2017. Scenes were filmed in Concord, Massachusetts,Clinton, Massachusetts,Framingham, Massachusetts, Lawrence, Massachusetts and Great Barrington, Massachusetts. The film was released in the United States on November 10, 2017. ""Daddy's Home 2"" was released on Digital HD on February 6, 2018, and was released on Blu-ray and DVD on February 20, "Daddy's Home 2"
           Roger (John Cena), to the cabin for Christmas. That evening, the entire family takes part in a Christmas manger representation. Brad gets into a fight with Dusty because he wants to play Joseph, which Dusty is currently playing. When Megan begins to swear, and Adrianna falls from being drunk, the crowd breaks up. Instead of Dusty fighting Brad, he almost comes to blows with Roger, and Don is repeatedly hit with ice-balls. The next morning, Christmas Day, the families all pack up to leave. On their way out of town, the families are forced back to town on account of "Daddy's Home (film)"
           that Will Ferrell and Mark Wahlberg would play the lead roles in the film. On November 12, Linda Cardellini joined the cast of the film, to play Ferrell's character's wife. On November 18, Hannibal Buress joined the film to play a sarcastic handyman. On January 28, 2015, Paul Scheer was added to the cast of the film, playing The Whip, a crazy DJ. Principal photography began on November 17, 2014, in New Orleans, Louisiana. On November 24 and 25, filming took place at Edward Hynes Charter School. On January 12, 2015, actors were spotted filming in the Lakeview area. On "Daddy's Home (film)"
           of 42 out of 100, based on 30 critics, indicating ""mixed or average reviews"". Audiences polled by CinemaScore gave the film an average grade of ""B+"" on an A+ to F scale. Will Ferrell was nominated for a Teen Choice Award in the category Choice Movie Actor in a Comedy. In April 2016, a sequel was announced with Will Ferrell and Mark Wahlberg reprising their characters. Anders and John Morris wrote the script and Anders directed. In January 2017, Paramount Pictures courted Mel Gibson and John Lithgow to star in the sequel. The two were later confirmed to star in

           Question: who plays dylan in daddy's home 2
           Ground-Truth Answers: "Owen Vaccaro"
           Candidate: Vaccaro

           Is the candidate correct?
           Owen Vaccaro plays Dylan in the movie "Daddy's Home 2". Vaccaro is the last name. Answer based on explanation: yes.

           ###
           Compulsory format for the `Is the candidate correct?` question's answer:
           "Explanation: `Explanation for the answer based on the knowledge`. Answer based on explanation: `yes or no`.".
           Note: If candidate answer is 'unknown' then it is incorrect. Please remember do not answer it correct or yes.
           Now make prediction for following data.

           Comprehend following context: {passage}

           Question: {q}
           Ground-Truth Answers: {answers}
           Candidate: {candidate_answer}

           Is the candidate correct?
    """
    response = infer_vicuna(prompt)
    cleaned_response = response.lower().rstrip(".").strip("\"")
    if cleaned_response.endswith("yes") or cleaned_response.startswith("yes"):
        acceptable = "Yes"
    elif "candidate answer is correct" in cleaned_response:
        acceptable = "Yes"
    elif cleaned_response.endswith("no") or cleaned_response.startswith("no"):
        acceptable = "No"
    elif "candidate answer is incorrect" in cleaned_response:
        acceptable = "No"
    else:
        acceptable = ""
        logger.warning(f"Invalid response to `{q}` & `{candidate_answer}`: {response}")
        logger.warning(f"Prompt: {prompt}")

    return int(acceptable == "Yes"), response


def em_eval(question: Question, candidate_answer: str, match: str = "string") -> int:
    if not question.gold_answers:
        if question.is_unacceptable(candidate_answer):
            return 0
        else:
            return -1

    return int(
        metric_max_over_ground_truths(
            regex_match if match == "regex" else exact_match_score,
            candidate_answer,
            question.gold_answers,
        )
    )


def f1_eval(question: Question, candidate_answer: str) -> float:
    if not question.gold_answers:
        if question.is_unacceptable(candidate_answer):
            return 0
        else:
            return -1

    return metric_max_over_ground_truths(
        f1_score,
        candidate_answer,
        question.gold_answers,
    )


def _load_evaluated(output_file: os.PathLike) -> Mapping[str, Tuple[int, str]]:
    tokenizer = SimpleTokenizer()

    cached = {}
    with open(output_file, "r") as f:
        r = csv.reader(f, delimiter="\t")
        next(r)

        for row in r:
            if len(row) < 8:
                continue

            gpt = int(row[6])
            resp = row[7]

            q = tokenizer.tokenize(row[1], as_string=True).lower()
            ans = row[2]
            cached[f"{q}|{ans}"] = (gpt, resp)

    return cached


def evaluate(
    question: str,
    candidate_answer: str,
    gold_answers: Union[Set[str], Sequence[str]],
    openai_proxy: Optional[OpenAIProxy] = None,
    openai_model: str = "text-davinci-003",
    max_tokens: int = 100,
    temperature: float = 1.0,
) -> Mapping[str, float]:

    if openai_proxy is None:
        openai_proxy = OpenAIProxy(openai_model, max_tokens, temperature)

    q = Question(question, gold_answers)
    gpt_result, gpt_response = gpt_eval(q, candidate_answer, openai_proxy)
    em = em_eval(q, candidate_answer)
    f1 = f1_eval(q, candidate_answer)

    return {"em": em, "f1": f1, openai_proxy.model_name: gpt_result}


def evaluate_file(
    predict_file: os.PathLike,
    dataset_file: Optional[os.PathLike] = None,
    annotation_file: Optional[os.PathLike] = None,
    output_file: Optional[os.PathLike] = None,
    openai_model: Optional[str] = None,
    openai_model_bool: Optional[bool] = False,
    max_tokens: int = 100,
    temperature: float = 0.0,
    overwrite_cache: bool = False,
    return_per_sample: bool = False,
) -> Mapping[str, Union[float, List[float]]]:
    predict_file = Path(predict_file)

    if output_file:
        output_path = Path(output_file)
    else:
        output_name = f"{predict_file.stem}_eval"
        if openai_model:
            output_name += f"-{openai_model}"
        if annotation_file:
            annotation_name = Path(annotation_file).stem
            output_name += f"-{annotation_name[annotation_name.index('_') + 1:]}"

        output_path = predict_file.parent / f"{output_name}.tsv"

    if openai_model and openai_model_bool:
        openai_proxy = OpenAIProxy(openai_model, max_tokens, temperature)
    elif openai_model:
        openai_proxy = openai_model
    else:
        openai_proxy = None

    if dataset_file is not None:
        questions = list(read_questions(dataset_file))
    else:
        questions = None

    eval_result = _evaluate(predict_file, questions, openai_proxy, output_path, annotation_file, overwrite_cache)
    questions = eval_result.pop("questions")

    if openai_proxy and openai_model_bool:
        logger.info(f"OpenAI API call stats: {openai_proxy.get_stats()}")

    if "AnnotatedEM" in eval_result and len(eval_result["EM"]) < len(questions):
        logger.info(
            f"Only questions found in annotation file were evaluated: {len(eval_result['EM'])} out of {len(questions)}"
        )

    return {metric: scores if return_per_sample else np.mean(scores) for metric, scores in eval_result.items()}


def _evaluate(
    predict_file: os.PathLike,
    questions: Optional[Sequence[Question]],
    openai_proxy: Optional[OpenAIProxy],
    output_file: os.PathLike,
    annotation_file: Optional[os.PathLike] = None,
    overwrite_cache: bool = False,
) -> Mapping[str, list]:
    predicted_dict, questions = read_predict_file(
        predict_file,
        questions,
    )

    if annotation_file and os.path.exists(annotation_file):
        annotated_answers = read_annotations(annotation_file)
    else:
        annotated_answers = {}

    cached_output = {}
    if os.path.exists(output_file) and not overwrite_cache:
        cached_output = _load_evaluated(output_file)

    em_scores, f1_scores = [], []
    annotated_em_scores = []
    gpt_scores = []

    with open(output_file, "w") as f:
        w = csv.writer(f, delimiter="\t")
        headers = ["id", "Question", "Gold answers", "Model answer", "EM", "F1"]
        if annotated_answers:
            headers.append("AnnotatedEM")

        if isinstance(openai_proxy, OpenAIProxy):
            headers.extend([openai_proxy.model_name, "Response"])
        elif isinstance(openai_proxy, str):
            headers.extend([openai_proxy, "Response"])

        w.writerow(headers)

        for question in tqdm(questions):
            qkey = question.tokenized_text.lower()
            if annotated_answers and qkey not in annotated_answers:
                continue

            if qkey not in predicted_dict:
                logger.warning(f"Question not found in prediction file and thus skipped: `{question.text}`")
                continue

            if not question.has_annotated_answers:
                logger.warning(f"Question with no annotated answers skipped: `{question.text}`")
                continue

            predicted_answer = predicted_dict[qkey]
            em = em_eval(question, predicted_answer)
            f1 = f1_eval(question, predicted_answer)

            if em < 0 or f1 < 0:
                logger.warning(
                    f"Predicted answer could not be evaluated: `{question.text}` -> `{predicted_answer}` vs. {question.gold_answers}"
                )
                continue

            row = [question.id, question.text, question.answers, predicted_answer, em, f1]

            if annotated_answers and qkey in annotated_answers:
                question.update_answers(annotated_answers[qkey])
                annotated_em = em_eval(question, predicted_answer)
                if annotated_em < 0:
                    logger.warning(
                        f"Predicted answer could not be evaluated after applying annotations: `{question.text}` -> `{predicted_answer}` vs. {question.gold_answers}"
                    )
                    continue

                annotated_em_scores.append(annotated_em)
                row.append(annotated_em)

            if openai_proxy:
                cache_key = f"{question.text}|{predicted_answer}"
                if cache_key not in cached_output:
                    if isinstance(openai_proxy, OpenAIProxy):
                        gpt_result, gpt_response = gpt_eval(question, predicted_answer, openai_proxy)
                    else:
                        gpt_result, gpt_response = vicuna_eval(question, predicted_answer)
                else:
                    gpt_result, gpt_response = cached_output[cache_key]

                gpt_scores.append(gpt_result)
                row.extend((gpt_result, gpt_response))

            em_scores.append(em)
            f1_scores.append(f1)

            w.writerow(row)
            f.flush()

    eval_result = {
        "questions": questions,
        "EM": em_scores,
        "F1": f1_scores,
    }

    if annotated_answers:
        eval_result["AnnotatedEM"] = annotated_em_scores

    if openai_proxy:
        if isinstance(openai_proxy, OpenAIProxy):
            eval_result[openai_proxy.model_name] = gpt_scores
        else:
            eval_result[openai_proxy] = gpt_scores

    return eval_result
