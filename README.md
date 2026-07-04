# Nipuna AI Assistant

Production-grade business Q&A backend built on LangGraph with explicit source routing, grounding, and citation metadata.

## Graph flow

`classify_intent -> route_to_source -> retrieve -> ground_and_verify -> generate_answer`

If the query is ambiguous or retrieval returns nothing reliable, the graph branches to `clarify` instead of guessing.

### Diagram

```text
START
  -> classify_intent
      -> clarify                      if ambiguous
      -> generate_answer              if general/non-business
      -> route_to_source              if business retrieval/action is needed
           -> retrieve                executes connected integrations in parallel
                -> clarify            if no data or insufficient support
                -> ground_and_verify   verifies every claim against retrieved context
                     -> clarify        if unsupported claims remain
                     -> generate_answer produces grounded answer with citations
                           -> END
      -> END
```

## Gmail reference implementation

Gmail is implemented end to end as the reference source:

- `gmail_search_emails`
- `gmail_get_email`
- `gmail_send_email`

The local fixture connector makes the graph deterministic for development and evals. Set `NIPUNA_AI_GMAIL_MODE=live` to use the Composio-backed connector when available.

## API

`POST /chat`

Request:

```json
{
  "thread_id": "thread-123",
  "message": "Find overdue invoices in Gmail"
}
```

Response includes:

- `answer`
- `citations`
- `sources_queried`
- `confidence`
- `needs_clarification`
- `clarification_question`

## Run

```bash
uvicorn main:app --reload
```

## Eval

Run the local eval suite with:

```bash
pytest evals/test_answers.py -q
```

