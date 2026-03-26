# AI-INTERVIEW-ASSISTANT

A comprehensive AI-powered interview Assistant with proctoring capabilities. This project integrates Gemini AI for question generation and multimodal evaluation (voice, text, body language, facial expression), and YOLO for computer vision proctoring (tab-switching, person, and phone detection).

## Project Structure

```text
AI-interview/
├── backend/                  # Flask backend handling AI and Proctoring logic
│   ├── app.py                # Main Flask application and API endpoints
│   ├── evaluator.py          # Wrapper for evaluating candidate answers
│   ├── gemini_service.py     # Gemini AI integration (Questions & Multimodal Evaluation)
│   ├── utils.py              # Helper utility functions
│   ├── yolo_service.py       # YOLOv8 integration for proctoring/object detection
│   ├── yolov8n.pt            # Pre-trained YOLOv8 nano model weights
│   └── uploads/              # Directory for downloaded resumes (For HR role)
├── frontend/                 # Vanilla HTML/JS frontend
│   ├── assets/               # Media assets (e.g., background videos)
│   ├── css/                  # Stylesheets
│   │   └── style.css
│   ├── js/                   # Frontend logic
│   │   ├── main.js           # Setup and role selection logic
│   │   └── interview.js      # Core interview flow, webcam capture, voice, and timer
│   ├── index.html            # Landing page (Role & Question selection)
│   ├── interview.html        # Active interview dashboard
│   └── result.html           # Post-interview evaluation report
├── .env                      # Environment variables (You need to create this)
├── requirements.txt          # Python dependencies
└── README.md                 # Project documentation
```

## Step-by-Step Setup Process

Follow these instructions to run the AI Interview Assistant on your local machine.

### Step 1: Prerequisites
Ensure you have the following installed on your machine:
- **Python 3.10+**
- **pip** (Python package installer)
- A modern web browser (Google Chrome or Microsoft Edge recommended for Speech Recognition support).

### Step 2: Clone or Open the Project
Open the project folder (`AI-interview`) in your preferred IDE, such as Visual Studio Code.

### Step 3: Set Up Environment Variables
Create a file named `.env` in the root directory (`AI-interview/.env`). You will need a Google Gemini API Key.
Add the following lines to your `.env` file:
```env
# Your Google Gemini API Key
GEMINI_API_KEY=your_gemini_api_key_here

# Optional Configurations
GEMINI_MODEL=gemini-1.5-flash-latest
HR_SECRET_TOKEN=super-secret-hr-token-123
```

### Step 4: Install Dependencies
Open your terminal, navigate to the project root directory (`AI-interview`), and install the required Python packages:
```bash
pip install -r requirements.txt
```

*(Note: Depending on your system, you may need to use `pip3` instead of `pip` or set up a virtual environment `venv` first).*

### Step 5: Run the Backend Server
Start the Flask backend server from the root directory:
```bash
python backend/app.py
```
*(You should see output indicating that the server is running on `http://127.0.0.1:5000`)*

### Step 6: Access the Application
The Flask app serves the frontend directory.
1. Open your web browser.
2. Go to: [http://127.0.0.1:5000/](http://127.0.0.1:5000/)
3. You will see the AI Interview Assistant landing page.

### Step 7: How to Use the Assistant
1. **Landing Page:** Select a job role from the dropdown, choose the number of questions, and upload a resume if you select the "HR" role. Click "Start Interview".
2. **Camera Permissions:** Allow camera and microphone permissions when prompted by your browser.
3. **Interview Flow:**
   - The AI will display a question.
   - You can click **"Start voice"** to dictate your answer or type it out.
   - Click **"Submit & next"**.
   - **During your answer**, the system captures your voice and camera frames to analyze your sentiment, body language, and expressions.
4. **Feedback:** After submitting an answer, the AI provides a score, detailed feedback, communication analysis, actionable suggestions, perfect solutions, and an emotional sentiment analysis based on your combined voice/text and visual body language.
5. **Proctoring:** 
   - Ensure only one person is in the camera view.
   - Keep phones out of sight (or you will receive a warning).
   - If you switch tabs during the interview, the system will record a tab switch. If you switch tabs 3 times, the interview will automatically terminate.



<img width="1920" height="915" alt="{553765A2-683A-43FA-A8A5-03DE61ED3E07}" src="https://github.com/user-attachments/assets/d69c4fcd-9300-4e13-891f-77a598e44738" />
<img width="1902" height="914" alt="{608C794C-17EE-44B3-B129-BC5958FC11EE}" src="https://github.com/user-attachments/assets/7d18a022-de64-4ed4-82fc-5619ee848d07" />
<img width="1916" height="920" alt="{AD559FD4-F2F3-460B-A390-E30EB73B20F6}" src="https://github.com/user-attachments/assets/5249243a-5a2a-4c9e-8b3c-c9c052169f51" />
