import gsap from 'gsap'

const MOTION_QUERY = '(prefers-reduced-motion: reduce)'

function prefersReducedMotion() {
  return typeof window !== 'undefined' && window.matchMedia(MOTION_QUERY).matches
}

/** True when pointer coordinates fall outside the dialog panel (backdrop / page gutter). */
export function isOutsideDialogPanel(dialogEl, event) {
  if (!dialogEl?.open) return false
  const { left, right, top, bottom } = dialogEl.getBoundingClientRect()
  const { clientX: x, clientY: y } = event
  return x < left || x > right || y < top || y > bottom
}

/**
 * Dismiss modal when user clicks outside the dialog panel (backdrop area).
 * Uses capture phase so it works across browsers with native <dialog>.
 */
export function useBackdropDismiss(dialogRef, onClose) {
  function onPointerDown(event) {
    if (event.button !== 0) return
    const dialog = dialogRef.value
    if (!dialog?.open || !isOutsideDialogPanel(dialog, event)) return
    event.preventDefault()
    onClose()
  }

  function bind() {
    window.addEventListener('pointerdown', onPointerDown, true)
  }

  function unbind() {
    window.removeEventListener('pointerdown', onPointerDown, true)
  }

  return { bind, unbind }
}

/**
 * GSAP open/close for native <dialog> modals (panel + backdrop class).
 */
export function useModalAnimation() {
  let activeTween = null

  function killActive() {
    activeTween?.kill()
    activeTween = null
  }

  function openModal(dialogEl) {
    if (!dialogEl) return
    killActive()
    gsap.killTweensOf(dialogEl)
    dialogEl.showModal()

    if (prefersReducedMotion()) {
      dialogEl.classList.add('modal-backdrop-in')
      return
    }

    dialogEl.classList.remove('modal-backdrop-in')
    requestAnimationFrame(() => {
      dialogEl.classList.add('modal-backdrop-in')
    })

    gsap.set(dialogEl, { opacity: 0, scale: 0.96, y: 14 })
    activeTween = gsap.to(dialogEl, {
      opacity: 1,
      scale: 1,
      y: 0,
      duration: 0.38,
      ease: 'power3.out',
      onComplete: () => {
        gsap.set(dialogEl, { clearProps: 'opacity,scale,y' })
        activeTween = null
      },
    })
  }

  function closeModal(dialogEl) {
    if (!dialogEl || !dialogEl.open) return Promise.resolve()
    killActive()

    if (prefersReducedMotion()) {
      dialogEl.classList.remove('modal-backdrop-in')
      dialogEl.close()
      return Promise.resolve()
    }

    dialogEl.classList.remove('modal-backdrop-in')
    return new Promise((resolve) => {
      activeTween = gsap.to(dialogEl, {
        opacity: 0,
        scale: 0.98,
        y: 10,
        duration: 0.28,
        ease: 'power2.in',
        onComplete: () => {
          dialogEl.close()
          gsap.set(dialogEl, { clearProps: 'opacity,scale,y' })
          activeTween = null
          resolve()
        },
      })
    })
  }

  return { openModal, closeModal, killActive }
}
