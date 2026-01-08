import random

QUESTIONS = [
    {
        "id": "q1",
        "difficulty": "easy",
        "question": "Quem construiu a arca?",
        "options": ["Moisés", "Noé", "Abraão", "Davi"],
        "correctIndex": 1,
    },
    {
        "id": "q2",
        "difficulty": "medium",
        "question": "Quantos discípulos Jesus escolheu como apóstolos?",
        "options": ["10", "11", "12", "13"],
        "correctIndex": 2,
    },
    {
        "id": "q3",
        "difficulty": "hard",
        "question": "Qual profeta enfrentou os profetas de Baal no Monte Carmelo?",
        "options": ["Isaías", "Jeremias", "Elias", "Ezequiel"],
        "correctIndex": 2,
    },
    {
        "id": "q4",
        "difficulty": "apocalyptic",
        "question": "Quantas igrejas são mencionadas no Apocalipse (capítulos 2 e 3)?",
        "options": ["5", "6", "7", "8"],
        "correctIndex": 2,
    },
]


def get_random_question():
    return random.choice(QUESTIONS).copy()
