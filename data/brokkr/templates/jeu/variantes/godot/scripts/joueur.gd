extends CharacterBody2D

const VITESSE := 300.0


func _physics_process(_delta: float) -> void:
	var direction := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity = direction * VITESSE
	move_and_slide()
