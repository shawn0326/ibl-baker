//! Private Windows phase/heap instrumentation; never linked into production.
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{
    AtomicBool, AtomicUsize,
    Ordering::{Acquire, Relaxed, Release},
};
use std::time::{Duration, Instant};

const CAPACITY: usize = 256;
static LIVE: AtomicUsize = AtomicUsize::new(0);
static CURRENT: AtomicUsize = AtomicUsize::new(0);
static NEXT: AtomicUsize = AtomicUsize::new(1);
static STOP: AtomicBool = AtomicBool::new(false);
static STAGES: [Stage; CAPACITY] = [const { Stage::new() }; CAPACITY];

struct Stage {
    parent: AtomicUsize,
    heap_peak: AtomicUsize,
    commit_peak: AtomicUsize,
    samples: AtomicUsize,
}

impl Stage {
    const fn new() -> Self {
        Self {
            parent: AtomicUsize::new(0),
            heap_peak: AtomicUsize::new(0),
            commit_peak: AtomicUsize::new(0),
            samples: AtomicUsize::new(0),
        }
    }
}

fn observe_heap(live: usize) {
    let mut index = CURRENT.load(Acquire);
    while index != 0 {
        STAGES[index].heap_peak.fetch_max(live, Relaxed);
        index = STAGES[index].parent.load(Relaxed);
    }
}

struct Tracked;
#[global_allocator]
static ALLOCATOR: Tracked = Tracked;

unsafe impl GlobalAlloc for Tracked {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc(layout) };
        if !pointer.is_null() {
            observe_heap(LIVE.fetch_add(layout.size(), Relaxed) + layout.size());
        }
        pointer
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        let pointer = unsafe { System.alloc_zeroed(layout) };
        if !pointer.is_null() {
            observe_heap(LIVE.fetch_add(layout.size(), Relaxed) + layout.size());
        }
        pointer
    }
    unsafe fn dealloc(&self, pointer: *mut u8, layout: Layout) {
        LIVE.fetch_sub(layout.size(), Relaxed);
        unsafe { System.dealloc(pointer, layout) };
    }
    unsafe fn realloc(&self, pointer: *mut u8, layout: Layout, size: usize) -> *mut u8 {
        let result = unsafe { System.realloc(pointer, layout, size) };
        if !result.is_null() {
            if size >= layout.size() {
                observe_heap(LIVE.fetch_add(size - layout.size(), Relaxed) + size - layout.size());
            } else {
                LIVE.fetch_sub(layout.size() - size, Relaxed);
            }
        }
        result
    }
}

#[repr(C)]
struct Counters {
    cb: u32,
    faults: u32,
    peak_working_set: usize,
    working_set: usize,
    peak_paged: usize,
    paged: usize,
    peak_nonpaged: usize,
    nonpaged: usize,
    pagefile: usize,
    peak_pagefile: usize,
    private: usize,
}
#[link(name = "kernel32")]
unsafe extern "system" {
    fn GetCurrentProcess() -> *mut std::ffi::c_void;
}
#[link(name = "psapi")]
unsafe extern "system" {
    fn GetProcessMemoryInfo(
        process: *mut std::ffi::c_void,
        counters: *mut Counters,
        size: u32,
    ) -> i32;
}

fn private_commit() -> usize {
    let mut counters: Counters = unsafe { std::mem::zeroed() };
    counters.cb = std::mem::size_of::<Counters>() as u32;
    let ok = unsafe { GetProcessMemoryInfo(GetCurrentProcess(), &mut counters, counters.cb) };
    assert_ne!(ok, 0, "Private profile memory query failed");
    counters.private
}

fn observe_commit(value: usize) {
    let mut index = CURRENT.load(Acquire);
    while index != 0 {
        STAGES[index].commit_peak.fetch_max(value, Relaxed);
        STAGES[index].samples.fetch_add(1, Relaxed);
        index = STAGES[index].parent.load(Relaxed);
    }
}

pub fn start_sampling() {
    std::thread::spawn(|| {
        while !STOP.load(Relaxed) {
            observe_commit(private_commit());
            std::thread::sleep(Duration::from_millis(1));
        }
    });
}
pub fn stop_sampling() {
    STOP.store(true, Relaxed);
}

pub struct Scope {
    name: &'static str,
    id: usize,
    parent: usize,
    start: Instant,
    heap_start: usize,
    commit_start: usize,
}
pub fn scope(name: &'static str) -> Scope {
    let id = NEXT.fetch_add(1, Relaxed);
    assert!(id < CAPACITY, "Private profile stage capacity exceeded");
    let parent = CURRENT.load(Acquire);
    STAGES[id].parent.store(parent, Relaxed);
    let heap_start = LIVE.load(Relaxed);
    STAGES[id].heap_peak.store(heap_start, Relaxed);
    let commit_start = private_commit();
    STAGES[id].commit_peak.store(commit_start, Relaxed);
    CURRENT.store(id, Release);
    Scope {
        name,
        id,
        parent,
        start: Instant::now(),
        heap_start,
        commit_start,
    }
}
impl Drop for Scope {
    fn drop(&mut self) {
        let elapsed = self.start.elapsed().as_secs_f64();
        let heap_end = LIVE.load(Relaxed);
        let commit_end = private_commit();
        observe_heap(heap_end);
        observe_commit(commit_end);
        CURRENT.store(self.parent, Release);
        eprintln!(
            "IBL_PHASE\t{}\t{}\t{}\t{elapsed:.9}\t{}\t{}\t{heap_end}\t{}\t{}\t{commit_end}\t{}",
            self.id,
            self.parent,
            self.name,
            self.heap_start,
            STAGES[self.id].heap_peak.load(Relaxed),
            self.commit_start,
            STAGES[self.id].commit_peak.load(Relaxed),
            STAGES[self.id].samples.load(Relaxed)
        );
    }
}
