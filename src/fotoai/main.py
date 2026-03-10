class FotoApp:
    def __init__(self):
        self.name = "FotoAI"
        self.version = "0.1.0"

    def get_greeting(self) -> str:
        return f"Welcome to {self.name} v{self.version}"


def main():
    app = FotoApp()
    print(app.get_greeting())


if __name__ == "__main__":
    main()
