from app.db.mongodb import mongo_manager
from app.models.user import UserType
from app.repositories.user_repository import UserRepository
from app.services.auth_service import AuthService, EmailAlreadyRegisteredError


def prompt(label: str) -> str:
    return input(f"{label}: ").strip()


def main() -> None:
    mongo_manager.connect()
    try:
        repository = UserRepository(mongo_manager.users_collection())
        service = AuthService(repository)

        name = prompt("Admin name")
        email = prompt("Admin email")
        password = prompt("Admin password")

        service.register(
            name=name,
            email=email,
            password=password,
            user_types=[UserType.PLATFORM_USER],
            user_configuration={},
        )
        print("Admin user created successfully.")
    except EmailAlreadyRegisteredError:
        print("A user with that email already exists.")
    finally:
        mongo_manager.close()


if __name__ == "__main__":
    main()
