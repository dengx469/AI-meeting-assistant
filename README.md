# 📧 AI Email Scheduling Assistant

This project is an AI-powered system designed to automate the process of scheduling meetings directly from unstructured email threads. It uses Large Language Models (LLMs) to understand scheduling intent, find mutually agreeable times, and automatically manage Google Calendar.

## ✨ Key Features

* **Intelligent Scheduling Automation:** Automatically analyzes email content to identify potential meeting times and scheduling conflicts.
* **LLM Contextual Understanding:** Utilizes **LangChain** and integrated **LLMs (DeepSeek/Gemini)** to extract scheduling intents and detect contextual conflicts across email threads, significantly improving natural language processing accuracy.
* **Automated Calendar Management:** Automatically creates calendar events, generates **Google Meet** links, and sends invitations using the **Google Calendar API** and **Gmail API**.
* **Scalable Architecture:** Designed for asynchronous performance on the cloud, leveraging **Cloud Pub/Sub** for webhook handling from Gmail.
* **Robust State Management:** Includes sophisticated logic for retrying previously failed messages and maintaining Gmail history IDs for efficient, uninterrupted processing.

## 💻 Technologies Used

| Category | Technology | Files/Components |
| :--- | :--- | :--- |
| **Backend/Framework** | Python (Flask), Docker | `app_safe.py`, `Dockerfile` |
| **AI/LLM** | LangChain, DeepSeek API, Gemini API | `deepseek_client.py`, `app_safe.py` |
| **APIs/Services** | Gmail API, Google Calendar API | `gmail_utils.py`, `calendar_utils.py` |
| **Deployment** | Google Cloud Run, Cloud Pub/Sub | `app_safe.py`, `Dockerfile` |

## 🚀 Deployment and Setup

The application is structured for easy deployment as a containerized service, ideal for serverless platforms like Google Cloud Run.

### 1. Prerequisites
* Google Cloud Project configured with **Gmail** and **Google Calendar APIs**.
* Generated Google OAuth `token.json` file.
* **DEEPSEEK\_API\_KEY** or **GEMINI\_API\_KEY** set as environment variables.

### 2. Local Execution (for testing)

You can run the core logic directly via the `main()` function in `app_safe.py`:

```bash
# Ensure all required environment variables are set before execution
python app_safe.py