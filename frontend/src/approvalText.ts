// Who decided an approval, in words that stay true in a replay: only a click by the presenter is "you".

export const RECORDING_NOTE = 'in the recording this was approved'

export function decidedBy(by: string): string {
  switch (by) {
    case 'human':
      return 'decided by you'
    case 'recording':
      return 'approved during recording'
    case 'recording-auto':
      return 'auto-approved (recording)'
    case 'timeout':
      return 'timed out (denied)'
    default:
      return `decided by ${by || 'the system'}`
  }
}
